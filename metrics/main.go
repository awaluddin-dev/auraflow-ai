package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"runtime"
	"time"

	_ "github.com/lib/pq"
	"github.com/redis/go-redis/v9"
)

type HealthResponse struct {
	Status    string            `json:"status"`
	Timestamp string            `json:"timestamp"`
	Service   string            `json:"service"`
	Services  map[string]string `json:"services"`
}

type MetricsResponse struct {
	UptimeSeconds int64  `json:"uptime_seconds"`
	GoVersion     string `json:"go_version"`
	NumGoroutine  int    `json:"num_goroutine"`
	MemoryAllocMB uint64 `json:"memory_alloc_mb"`
}

var startTime = time.Now()

var (
	redisClient *redis.Client
	db          *sql.DB
)

func initConnections() {
	redisURL := os.Getenv("REDIS_URL")
	if redisURL == "" {
		redisURL = "redis://localhost:6379"
	}
	opts, err := redis.ParseURL(redisURL)
	if err == nil {
		redisClient = redis.NewClient(opts)
	} else {
		log.Printf("Failed to parse REDIS_URL: %v", err)
	}

	dbURL := os.Getenv("AURAFLOW_DATABASE_URL")
	if dbURL == "" {
		// Fallback to DATABASE_URL if AURAFLOW_DATABASE_URL is not set
		dbURL = os.Getenv("DATABASE_URL")
	}
	if dbURL != "" {
		database, err := sql.Open("postgres", dbURL)
		if err == nil {
			db = database
		} else {
			log.Printf("Failed to open DB: %v", err)
		}
	} else {
		log.Println("AURAFLOW_DATABASE_URL and DATABASE_URL are not set")
	}
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	services := make(map[string]string)
	overallStatus := "ok"

	// Check Redis
	if redisClient != nil {
		if err := redisClient.Ping(ctx).Err(); err != nil {
			services["redis"] = "down"
			overallStatus = "degraded"
		} else {
			services["redis"] = "up"
		}
	} else {
		services["redis"] = "not_configured"
	}

	// Check Database
	if db != nil {
		if err := db.PingContext(ctx); err != nil {
			services["postgres"] = "down"
			overallStatus = "degraded"
		} else {
			services["postgres"] = "up"
		}
	} else {
		services["postgres"] = "not_configured"
	}

	resp := HealthResponse{
		Status:    overallStatus,
		Timestamp: time.Now().UTC().Format(time.RFC3339),
		Service:   "auraflow-metrics",
		Services:  services,
	}

	w.Header().Set("Content-Type", "application/json")
	if overallStatus == "degraded" {
		w.WriteHeader(http.StatusServiceUnavailable)
	} else {
		w.WriteHeader(http.StatusOK)
	}
	json.NewEncoder(w).Encode(resp)
}

func metricsHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var m runtime.MemStats
	runtime.ReadMemStats(&m)

	resp := MetricsResponse{
		UptimeSeconds: int64(time.Since(startTime).Seconds()),
		GoVersion:     runtime.Version(),
		NumGoroutine:  runtime.NumGoroutine(),
		MemoryAllocMB: m.Alloc / 1024 / 1024,
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(resp)
}

func main() {
	initConnections()

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/metrics", metricsHandler)

	log.Printf("Starting metrics service on port %s...\n", port)

	server := &http.Server{
		Addr:         ":" + port,
		Handler:      mux,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 10 * time.Second,
		IdleTimeout:  15 * time.Second,
	}

	if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("Could not listen on port %s: %v\n", port, err)
	}
}
