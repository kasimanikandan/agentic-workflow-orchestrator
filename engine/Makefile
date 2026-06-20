BIN      := orchestrator
PKG      := ./cmd/orchestrator
PROTO    := ../proto/orchestrator.proto
OUT_PROTO := transport/grpc/gen

.PHONY: build test proto clean

## Build the engine binary.
build:
	go build -o $(BIN) $(PKG)

## Run all unit tests.
test:
	go test ./...

## Generate gRPC + protobuf Go code (requires protoc + plugins).
## Install:
##   brew install protobuf
##   go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
##   go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest
proto:
	mkdir -p $(OUT_PROTO)
	protoc --proto_path=../proto \
	       --go_out=$(OUT_PROTO) --go_opt=paths=source_relative \
	       --go-grpc_out=$(OUT_PROTO) --go-grpc_opt=paths=source_relative \
	       $(PROTO)

clean:
	rm -f $(BIN)
	rm -rf $(OUT_PROTO)
