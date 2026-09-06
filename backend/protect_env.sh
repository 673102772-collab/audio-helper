# Intercept `cp .env.example .env` so an existing .env is not overwritten.
cp() {
  _ah_src=""
  _ah_dst=""
  for _ah_arg in "$@"; do
    case "$_ah_arg" in
      -*) ;;
      *)
        if [ -z "$_ah_src" ]; then
          _ah_src=$_ah_arg
        else
          _ah_dst=$_ah_arg
        fi
        ;;
    esac
  done
  _ah_src_base="${_ah_src##*/}"
  _ah_dst_base="${_ah_dst##*/}"
  if [ "$_ah_src_base" = ".env.example" ] && [ "$_ah_dst_base" = ".env" ] && [ -e "$_ah_dst" ]; then
    echo "skip overwrite: $_ah_dst already exists" >&2
    unset _ah_src _ah_dst _ah_arg _ah_src_base _ah_dst_base
    return 0
  fi
  unset _ah_src _ah_dst _ah_arg _ah_src_base _ah_dst_base
  command cp "$@"
}
