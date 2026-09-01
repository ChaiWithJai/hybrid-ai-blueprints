# bonsai_edge developer entry points. Run from edge/mobile/boilerplate/.

SERVER := ../bonsai_edge_server/bonsai_edge_server
DEMO   ?= 01

.PHONY: bootstrap dev check generate drift test

bootstrap:
	./bootstrap.sh

dev:
	./tmux-dev.sh $(DEMO)

generate:
	cd $(SERVER) && serverpod generate

# CI gate: regenerating must produce zero diff (mirrors serverpod's own CI;
# see the codegen-asymptote note in boilerplate/README.md)
drift: generate
	git diff --exit-code -- $(SERVER)

test:
	cd $(SERVER) && dart test

check: drift test
	cd $(SERVER) && dart analyze
