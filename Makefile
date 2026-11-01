.PHONY: all starter full validate audit repro test docs
all: starter full validate audit repro test
starter: ; python -m freight_audit generate --profile starter
full: ; python -m freight_audit generate --profile full
validate: ; python -m freight_audit validate --profile full
audit: ; python -m freight_audit audit --profile full
repro: ; python -m freight_audit repro --profile full
test: ; python -m pytest -q
docs: ; python -m freight_audit docs
