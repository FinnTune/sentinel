// Command gateway runs the Sentinel webhook gateway.
package main

import (
	"log"
	"net/http"
	"time"

	"github.com/FinnTune/sentinel/gateway"
)

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", gateway.HealthHandler)

	srv := &http.Server{
		Addr:              ":8080",
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	log.Printf("gateway listening on %s", srv.Addr)
	log.Fatal(srv.ListenAndServe())
}
