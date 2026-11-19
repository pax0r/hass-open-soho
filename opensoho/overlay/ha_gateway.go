package main

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/netip"
	"path"
	"regexp"
	"slices"
	"strings"
	"time"

	"github.com/pocketbase/pocketbase/core"
)

// Home Assistant's app Ingress guide designates this address as the only
// trusted peer. The Supervisor assigns it explicitly on the hassio bridge.
var supervisorPeer = netip.MustParseAddr("172.30.32.2")

var (
	ingressPath = regexp.MustCompile(`^/api/hassio_ingress/[A-Za-z0-9_-]{1,256}$`)
	haUserID    = regexp.MustCompile(`^[a-f0-9]{32}$`)
)

const (
	haUIHeader = "X-OpenSOHO-UI"
	sessionAPI = "/api/ha/session"
	monitorAPI = "/api/v1/monitoring/device"
	panelCSP   = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'self'"
)

func canonicalURL(r *http.Request) bool {
	return r.URL.RawPath == "" && canonicalPath(r.URL.Path)
}

func canonicalPath(p string) bool {
	return strings.HasPrefix(p, "/") && !strings.ContainsAny(p, "\\\x00") &&
		(p == "/" || path.Clean(p) == strings.TrimSuffix(p, "/"))
}

func stripClientHeaders(r *http.Request, ingress bool) {
	if ingress {
		r.Header.Del("Authorization")
		r.Header.Del("Origin")
	}
	for name := range r.Header {
		nameLower := strings.ToLower(name)
		switch {
		case strings.HasPrefix(nameLower, "x-remote-user-"),
			strings.HasPrefix(nameLower, "x-forwarded-"),
			nameLower == "x-ingress-path", nameLower == "x-hass-source",
			nameLower == "forwarded",
			nameLower == "cookie", nameLower == "referer",
			nameLower == "x-supervisor-token", nameLower == "x-hassio-key":
			r.Header.Del(name)
		}
	}
}

func lanHandler(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		p := r.URL.Path
		if !canonicalPath(p) || strings.Contains(strings.ToLower(r.URL.RawPath), "%2f") ||
			atOrBelow(p, "/api/ha") ||
			(!strings.HasPrefix(p, "/api/") && !strings.HasPrefix(p, "/controller/")) {
			http.NotFound(w, r)
			return
		}
		r = r.Clone(r.Context())
		stripClientHeaders(r, false)
		w.Header().Set("Cache-Control", "no-store")
		next.ServeHTTP(w, r)
	})
}

func atOrBelow(p, root string) bool {
	return p == root || strings.HasPrefix(p, root+"/")
}

func isIngressAdmin(r *http.Request, trusted netip.Addr) bool {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return false
	}
	peer, err := netip.ParseAddr(host)
	if err != nil || peer.Unmap() != trusted {
		return false
	}
	id := r.Header.Values("X-Remote-User-Id")
	groups := r.Header.Values("X-Remote-User-Groups")
	return len(id) == 1 && haUserID.MatchString(id[0]) &&
		len(groups) == 1 && slices.Contains(strings.Split(groups[0], ","), "system-admin")
}

func ingressHandler(trusted netip.Addr, next http.Handler, admin *core.Record) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("Referrer-Policy", "no-referrer")
		prefix := r.Header.Values("X-Ingress-Path")
		if !isIngressAdmin(r, trusted) || len(prefix) != 1 || !ingressPath.MatchString(prefix[0]) {
			http.Error(w, "Open OpenSOHO from Home Assistant as an administrator.", http.StatusForbidden)
			return
		}
		fetchSite := r.Header.Get("Sec-Fetch-Site")
		read := r.Method == http.MethodGet || r.Method == http.MethodHead
		uiRequest := r.Header.Get(haUIHeader) == "1"
		if fetchSite == "cross-site" || fetchSite == "same-site" ||
			r.Method == http.MethodOptions || (!read && !uiRequest) {
			http.Error(w, "Request is outside the OpenSOHO panel.", http.StatusForbidden)
			return
		}
		p := r.URL.Path
		if !canonicalURL(r) || !allowedPanelPath(p, read, admin.Collection().Id) {
			http.NotFound(w, r)
			return
		}
		if p == "/" || p == "/_" {
			http.Redirect(w, r, prefix[0]+"/_/", http.StatusTemporaryRedirect)
			return
		}
		if p == sessionAPI {
			if r.Method != http.MethodGet || !uiRequest {
				http.NotFound(w, r)
				return
			}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]string{
				"id": admin.Id, "collectionName": core.CollectionNameSuperusers,
			})
			return
		}
		if strings.HasPrefix(p, "/_/") {
			w.Header().Set("Content-Security-Policy", panelCSP)
		}

		ctx := context.WithValue(r.Context(), ingressAccountKey{}, admin.Clone())
		if p == "/api/realtime" && read {
			// An open stream must reconnect through Supervisor to continue.
			var cancel context.CancelFunc
			ctx, cancel = context.WithTimeout(ctx, time.Minute)
			defer cancel()
		}
		r = r.Clone(ctx)
		stripClientHeaders(r, true)
		// Both protected files and backup downloads validate a file token
		// independently of RequestEvent.Auth in PocketBase.
		backupDownload := read && strings.HasPrefix(p, "/api/backups/") &&
			len(strings.Split(p, "/")) == 4
		if read && (strings.HasPrefix(p, "/api/files/") || backupDownload) {
			token, err := admin.NewFileToken()
			if err != nil {
				http.Error(w, "Cannot authorize file request.", http.StatusServiceUnavailable)
				return
			}
			query := r.URL.Query()
			query.Set("token", token)
			r.URL.RawQuery = query.Encode()
		}
		next.ServeHTTP(&panelResponse{ResponseWriter: w, prefix: prefix[0]}, r)
	})
}

func allowedPanelPath(p string, read bool, superuserCollectionID string) bool {
	switch {
	case p == "/" || p == "/_" || strings.HasPrefix(p, "/_/"):
		return read
	case !strings.HasPrefix(p, "/api/"):
		return false
	case atOrBelow(p, monitorAPI) || p == "/api/oauth2-redirect" ||
		p == "/api/files/token" || p == "/api/batch":
		return false
	}
	parts := strings.Split(p, "/")
	if len(parts) >= 4 && parts[2] == "collections" {
		if strings.EqualFold(parts[3], core.CollectionNameSuperusers) || parts[3] == superuserCollectionID {
			return false
		}
		if len(parts) >= 5 && (parts[4] == "impersonate" || strings.HasPrefix(parts[4], "auth-")) {
			return false
		}
	}
	return true
}

type panelResponse struct {
	http.ResponseWriter
	prefix string
}

func (w *panelResponse) WriteHeader(status int) {
	h := w.Header()
	if loc := h.Get("Location"); strings.HasPrefix(loc, "/") && !strings.HasPrefix(loc, "//") {
		h.Set("Location", w.prefix+loc)
	}
	w.ResponseWriter.WriteHeader(status)
}

func (w *panelResponse) Unwrap() http.ResponseWriter { return w.ResponseWriter }
