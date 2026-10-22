# Cloth simulation, dressing and 3D sewing (CPU only, headless Blender).
# Runs in the core env; Blender is a separate GPL binary (system package or below).
ENGINE_FAMILY=clothsim
ENGINE_ENV=core
ENGINE_QUEUE=cpu
ENGINE_WORKER=clothsim
ENGINE_CELERY_APP=clothsim_worker.worker.celery_app

engine_env() {
  if [ -z "${BLENDER_BIN:-}" ]; then
    if [ -x "$ENGINES_DIR/blender/blender" ]; then export BLENDER_BIN="$ENGINES_DIR/blender/blender"
    else export BLENDER_BIN=blender; fi
  fi
  command -v "$BLENDER_BIN" >/dev/null 2>&1 || [ -x "$BLENDER_BIN" ] \
    || warn "Blender not found — drape/dress/sew jobs will fail until: engine.sh install clothsim"
}

# Portable Blender LTS into engines/blender (skipped if one is on PATH).
engine_build() {
  if command -v blender >/dev/null 2>&1 || [ -x "$ENGINES_DIR/blender/blender" ]; then
    echo "   blender present"; return 0
  fi
  local ver=4.2.3 tmp; tmp="$(mktemp -d)"
  say "downloading Blender $ver LTS (portable)"
  curl -fL --progress-bar "https://download.blender.org/release/Blender4.2/blender-$ver-linux-x64.tar.xz" -o "$tmp/b.tar.xz"
  tar -xf "$tmp/b.tar.xz" -C "$tmp"
  mv "$tmp/blender-$ver-linux-x64" "$ENGINES_DIR/blender"
  rm -rf "$tmp"
}
