package main

import (
	"context"
	"database/sql"
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"log"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/pocketbase/pocketbase/apis"
	"github.com/pocketbase/pocketbase/core"
	"github.com/pocketbase/pocketbase/tools/hook"
	pbui "github.com/pocketbase/pocketbase/ui"
)

const (
	dataRoot = "/data"
	appUID   = 10001
)

//go:embed ha_ui
var ingressUI embed.FS

type addonOptions struct {
	SharedSecret     string `json:"shared_secret"`
	EnableNewDevices bool   `json:"enable_new_devices"`
}

func main() {
	contents, err := os.ReadFile(dataRoot + "/options.json")
	if err != nil {
		log.Fatal("cannot read /data/options.json: ", err)
	}
	var options addonOptions
	if err := json.Unmarshal(contents, &options); err != nil {
		log.Fatal("invalid add-on options JSON")
	}
	if len(options.SharedSecret) < 32 || strings.ContainsAny(options.SharedSecret, "\x00\r\n") {
		log.Fatal("set shared_secret to a random value of at least 32 characters")
	}
	syscall.Umask(0o077)
	if err := enterDataDirectory(); err != nil {
		log.Fatal("cannot prepare persistent data directory: ", err)
	}
	pbui.DistDirFS, err = fs.Sub(ingressUI, "ha_ui")
	if err != nil {
		log.Fatal(err)
	}
	os.Args = []string{
		os.Args[0], "serve", "--http", "0.0.0.0:8091",
		"--enableNewDevices=" + strconv.FormatBool(options.EnableNewDevices),
	}
	runOpenSOHO(options.SharedSecret)
}

func enterDataDirectory() error {
	// Open the dedicated directory without following a symlink. Keep the
	// Supervisor-owned options file and its directory permissions intact.
	root, err := os.OpenRoot(dataRoot)
	if err != nil {
		return err
	}
	defer root.Close()
	if err := root.Mkdir("opensoho", 0o700); err != nil && !errors.Is(err, os.ErrExist) {
		return err
	}
	dir, err := root.OpenFile("opensoho", syscall.O_DIRECTORY|syscall.O_NOFOLLOW|os.O_RDONLY, 0)
	if err != nil {
		return err
	}
	defer dir.Close()
	if os.Geteuid() == 0 {
		if err := dir.Chown(appUID, appUID); err != nil {
			return err
		}
		if err := dir.Chmod(0o700); err != nil {
			return err
		}
		if err := syscall.Setgroups(nil); err != nil {
			return err
		}
		if err := syscall.Setgid(appUID); err != nil {
			return err
		}
		if err := syscall.Setuid(appUID); err != nil {
			return err
		}
	}
	return dir.Chdir()
}

const ingressAccount = "ha-ingress@opensoho.invalid"

type ingressAccountKey struct{}

func bindHomeAssistant(app core.App) {
	agentServer := &http.Server{
		ReadHeaderTimeout: 10 * time.Second,
		ReadTimeout:       60 * time.Second,
		WriteTimeout:      60 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
	app.OnServe().Bind(&hook.Handler[*core.ServeEvent]{
		Priority: -10000,
		Func: func(e *core.ServeEvent) error {
			admin, err := loadIngressAccount(e.App)
			if err != nil {
				return fmt.Errorf("initialize the internal Ingress account: %w", err)
			}
			e.InstallerFunc = nil
			// Default PocketBase access logs include the full URL and referrer.
			e.Router.Unbind(apis.DefaultActivityLoggerMiddlewareId, apis.DefaultCorsMiddlewareId)
			e.Router.Bind(&hook.Handler[*core.RequestEvent]{
				Priority: apis.DefaultLoadAuthTokenMiddlewarePriority - 1,
				Func: func(request *core.RequestEvent) error {
					if account, ok := request.Request.Context().Value(ingressAccountKey{}).(*core.Record); ok {
						request.Auth = account
					}
					return request.Next()
				},
			})
			if err := e.Next(); err != nil {
				return err
			}

			mux := e.Server.Handler
			ingress := ingressHandler(supervisorPeer, mux, admin)
			e.Server.Handler = ingress
			listener, err := net.Listen("tcp4", "0.0.0.0:8090")
			if err != nil {
				return fmt.Errorf("start OpenWISP listener: %w", err)
			}
			agentServer.Handler = agentHandler(mux)
			go func() {
				if err := agentServer.Serve(listener); !errors.Is(err, http.ErrServerClosed) {
					log.Fatal("OpenWISP listener stopped: ", err)
				}
			}()
			log.Print("OpenWISP listener ready on :8090, Home Assistant Ingress on :8091")
			return nil
		},
	})
	app.OnTerminate().Bind(&hook.Handler[*core.TerminateEvent]{
		Priority: -10000,
		Func: func(e *core.TerminateEvent) error {
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			if err := agentServer.Shutdown(ctx); err != nil {
				_ = agentServer.Close()
			}
			return e.Next()
		},
	})
}

func loadIngressAccount(app core.App) (*core.Record, error) {
	record, err := app.FindAuthRecordByEmail(core.CollectionNameSuperusers, ingressAccount)
	if err == nil {
		return record, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return nil, err
	}
	collection, err := app.FindCachedCollectionByNameOrId(core.CollectionNameSuperusers)
	if err != nil {
		return nil, err
	}
	record = core.NewRecord(collection)
	record.SetEmail(ingressAccount)
	record.SetVerified(true)
	record.SetRandomPassword()
	if err := app.Save(record); err != nil {
		// Validation errors can contain fields from the account.
		return nil, errors.New("cannot create the internal account")
	}
	return record, nil
}
