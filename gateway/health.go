// Package gateway receives CI webhooks and enqueues triage jobs.
package gateway

import "net/http"

// HealthHandler reports that the gateway process is up.
func HealthHandler(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte("ok"))
}
