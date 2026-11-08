// Command gateway runs the Sentinel webhook gateway.
package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/FinnTune/sentinel/gateway"
)

func main() {
	secret := os.Getenv("GITHUB_WEBHOOK_SECRET")
	if secret == "" {
		log.Fatal("GITHUB_WEBHOOK_SECRET is required")
	}
	addr := ":" + envOr("PORT", "8080")

	queue := gateway.NewMemoryQueue(100)
	go drain(queue)

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", gateway.HealthHandler)
	mux.Handle("/webhook", &gateway.WebhookHandler{Secret: secret, Queue: queue})

	srv := &http.Server{
		Addr:              addr,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := srv.Shutdown(shutdownCtx); err != nil {
			log.Printf("shutdown: %v", err)
		}
	}()

	log.Printf("gateway listening on %s", addr)
	if err := srv.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}

// drain logs queued jobs. It stands in for the agent worker until that exists.
func drain(q *gateway.MemoryQueue) {
	for job := range q.Jobs() {
		log.Printf("job: %s run %d (%s) on %s", job.Repo, job.RunID, job.Workflow, job.Branch)
	}
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
