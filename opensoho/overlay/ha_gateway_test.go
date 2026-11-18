package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/pocketbase/pocketbase/core"
)

const (
	testUser   = "0123456789abcdef0123456789abcdef"
	testPrefix = "/api/hassio_ingress/random_path-x123"
	testUUID   = "bb27ca26-5875-413c-8bd9-0a8a1557c0a7"
)

func request(method, target string) *http.Request {
	r := httptest.NewRequest(method, target, nil)
	r.RemoteAddr = supervisorPeer.String() + ":12345"
	r.Header.Set("X-Remote-User-Id", testUser)
	r.Header.Set("X-Remote-User-Groups", "system-users,system-admin")
	r.Header.Set("X-Ingress-Path", testPrefix)
	r.Header.Set(haUIHeader, "1")
	return r
}

func TestIngressDeniesUntrustedRequests(t *testing.T) {
	denyNext := http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Error("unauthorized request reached PocketBase")
	})
	admin := core.NewRecord(core.NewAuthCollection(core.CollectionNameSuperusers))
	handler := ingressHandler(supervisorPeer, denyNext, admin)

	for _, tc := range []struct {
		name   string
		change func(*http.Request)
		status int
	}{
		{"forged LAN", func(r *http.Request) { r.RemoteAddr = "192.168.1.9:1234" }, 403},
		{"forwarded peer", func(r *http.Request) {
			r.RemoteAddr = "192.168.1.9:1234"
			r.Header.Set("X-Forwarded-For", supervisorPeer.String())
		}, 403},
		{"regular user", func(r *http.Request) { r.Header.Set("X-Remote-User-Groups", "system-users") }, 403},
		{"lookalike group", func(r *http.Request) { r.Header.Set("X-Remote-User-Groups", "system-admin-other") }, 403},
		{"missing role", func(r *http.Request) { r.Header.Del("X-Remote-User-Groups") }, 403},
		{"missing identity", func(r *http.Request) { r.Header.Del("X-Remote-User-Id") }, 403},
		{"missing prefix", func(r *http.Request) { r.Header.Del("X-Ingress-Path") }, 403},
		{"duplicate role header", func(r *http.Request) { r.Header.Add("X-Remote-User-Groups", "system-users") }, 403},
		{"external prefix", func(r *http.Request) { r.Header.Set("X-Ingress-Path", "//other.example") }, 403},
		{"cross-site", func(r *http.Request) { r.Header.Set("Sec-Fetch-Site", "cross-site") }, 403},
		{"cross-origin same-site", func(r *http.Request) { r.Header.Set("Sec-Fetch-Site", "same-site") }, 403},
		{"no UI header", func(r *http.Request) { r.Header.Del(haUIHeader) }, 404},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := request(http.MethodGet, sessionAPI)
			tc.change(r)
			w := httptest.NewRecorder()
			handler.ServeHTTP(w, r)
			if w.Code != tc.status {
				t.Fatalf("status = %d, want %d", w.Code, tc.status)
			}
		})
	}
}

func TestIngressRoutesAndSession(t *testing.T) {
	admin := core.NewRecord(core.NewAuthCollection(core.CollectionNameSuperusers))
	admin.Id = "internalAccount"
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if account := r.Context().Value(ingressAccountKey{}).(*core.Record); account.Id != admin.Id {
			t.Error("missing internal identity")
		}
		if r.Header.Get("Authorization") != "" || r.Header.Get("Cookie") != "" || r.Header.Get("X-Remote-User-Id") != "" {
			t.Error("client credentials reached PocketBase")
		}
		http.Redirect(w, r, "/_/redirected", http.StatusTemporaryRedirect)
	})
	handler := ingressHandler(supervisorPeer, next, admin)

	for _, tc := range []struct {
		method string
		target string
		status int
	}{
		{"GET", "/", 307},
		{"GET", sessionAPI, 200},
		{"GET", "/api/collections/devices/records", 307},
		{"GET", "/controller/checksum/" + testUUID + "/", 404},
		{"GET", "/api/./ha/session", 404},
		{"GET", "/api%2fha/session", 404},
		{"HEAD", "/api/collections/_superusers/records", 404},
		{"POST", "/api/collections/devices/impersonate/id", 404},
		{"POST", "/api/collections/_superusers/auth-refresh", 404},
		{"POST", "/api/files/token", 404},
		{"POST", "/api/batch", 404},
		{"OPTIONS", "/api/collections/devices/records", 403},
	} {
		t.Run(tc.method+" "+tc.target, func(t *testing.T) {
			r := request(tc.method, tc.target)
			r.Header.Set("Authorization", "client-token")
			r.Header.Set("Cookie", "ingress_session=example")
			w := httptest.NewRecorder()
			handler.ServeHTTP(w, r)
			if w.Code != tc.status {
				t.Fatalf("status = %d, want %d", w.Code, tc.status)
			}
			if tc.status == 307 && !strings.HasPrefix(w.Header().Get("Location"), testPrefix+"/_/") {
				t.Fatal("redirect escaped Ingress")
			}
			if tc.target == sessionAPI {
				var data map[string]string
				if err := json.Unmarshal(w.Body.Bytes(), &data); err != nil || len(data) != 2 || data["id"] != admin.Id {
					t.Fatal("unexpected session response")
				}
			}
		})
	}
}

func TestAgentListenerOnlyExposesOpenWISP(t *testing.T) {
	handler := agentHandler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Context().Value(ingressAccountKey{}) != nil || r.Header.Get("X-Remote-User-Groups") != "" ||
			r.Header.Get("Authorization") != "" || r.Header.Get("Cookie") != "" {
			t.Error("agent acquired panel identity")
		}
		if r.URL.Query().Get("key") != "test-key" {
			t.Error("OpenWISP key was not forwarded")
		}
		w.WriteHeader(http.StatusNoContent)
	}))
	for _, tc := range []struct {
		method string
		target string
		status int
	}{
		{"POST", "/controller/register/", 204},
		{"POST", "/controller/report-status/" + testUUID + "/", 204},
		{"POST", "/controller/update-info/" + testUUID + "/", 204},
		{"GET", "/controller/checksum/" + testUUID + "/", 204},
		{"GET", "/controller/download-config/" + testUUID + "/", 204},
		{"POST", "/api/v1/monitoring/device/", 204},
		{"GET", "/_/", 404},
		{"GET", sessionAPI, 404},
		{"POST", sessionAPI, 404},
		{"POST", "/api/collections/_superusers/auth-with-password", 404},
		{"GET", "/controller/checksum/" + testUUID, 404},
		{"GET", "/controller/checksum/../", 404},
		{"GET", "/controller//checksum/" + testUUID + "/", 404},
		{"PUT", "/controller/register/", 404},
	} {
		t.Run(tc.method+" "+tc.target, func(t *testing.T) {
			r := request(tc.method, tc.target+"?key=test-key")
			r.Header.Set("Authorization", "client-token")
			r.Header.Set("Cookie", "ingress_session=example")
			w := httptest.NewRecorder()
			handler.ServeHTTP(w, r)
			if w.Code != tc.status {
				t.Fatalf("status = %d, want %d", w.Code, tc.status)
			}
		})
	}
}
