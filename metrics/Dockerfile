FROM golang:1.22-alpine AS builder

WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download

COPY main.go ./

# Disable CGO to ensure a static binary that can run in scratch
RUN CGO_ENABLED=0 GOOS=linux go build -o auraflow-metrics main.go

FROM scratch

WORKDIR /
COPY --from=builder /app/auraflow-metrics .
EXPOSE 8080
CMD ["./auraflow-metrics"]
