#!/usr/bin/env bash
# Join the recorded talk parts into one video: the NN_name.mp4 files of a folder in slide order
# (NN is the part's first slide), each scaled to 1920x1080 at 30 fps and its sound normalized to
# -16 LUFS, so that every speaker is equally loud.
#
#   bash scripts/tools/stitch_talk.sh RECORDINGS_DIR [OUTPUT]    # RECORDINGS_DIR/talk_final.mp4
#
# Stops before encoding if the parts total more than 4:50 (STITCH_MAX_SECONDS, default 290).
# Needs ffmpeg and ffprobe (brew install ffmpeg, or apt install ffmpeg).
set -euo pipefail
export LC_ALL=C

dir="${1:?usage: stitch_talk.sh RECORDINGS_DIR [OUTPUT]}"
out="${2:-$dir/talk_final.mp4}"
max="${STITCH_MAX_SECONDS:-290}"

fail() { echo "stitch_talk: $*" >&2; exit 1; }
clock() { awk -v s="$1" 'BEGIN { s = int(s); printf "%d:%02d", s / 60, s % 60 }'; }
streams() { ffprobe -v error -select_streams "$1" -show_entries stream=index -of csv=p=0 "$2"; }

for tool in ffmpeg ffprobe; do
  command -v "$tool" > /dev/null || fail "$tool not found (brew install ffmpeg, or apt install ffmpeg)"
done
[ -d "$dir" ] || fail "$dir is not a folder"

shopt -s nullglob
parts=("$dir"/[0-9][0-9]_*.mp4)
[ ${#parts[@]} -gt 0 ] || fail "no NN_name.mp4 parts in $dir"

seen=" "
durations=()
total=0
for part in "${parts[@]}"; do
  name="$(basename "$part")"
  case "$seen" in *" ${name:0:2} "*) fail "two parts start at slide ${name:0:2}" ;; esac
  seen="$seen${name:0:2} "
  [ -n "$(streams v "$part")" ] || fail "$name has no video"
  [ -n "$(streams a "$part")" ] || fail "$name has no sound"
  seconds="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$part")"
  durations+=("$seconds")
  total="$(awk -v a="$total" -v b="$seconds" 'BEGIN { print a + b }')"
  printf '%-28s %6.1f s\n' "$name" "$seconds"
done
printf 'total %s (%.1f s)\n' "$(clock "$total")" "$total"
if awk -v t="$total" -v m="$max" 'BEGIN { exit !(t > m) }'; then
  fail "the parts total $(clock "$total"), over the $(clock "$max") limit; record again the part that runs past its seconds"
fi

inputs=()
filter=""
joined=""
for i in "${!parts[@]}"; do
  seconds="${durations[$i]}"
  inputs+=(-i "${parts[$i]}")
  # Both streams are cut to the part's length, so that sound and picture stay in step.
  filter+="[$i:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
  filter+="pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p,"
  filter+="tpad=stop_mode=clone:stop_duration=$seconds,trim=duration=$seconds,setpts=PTS-STARTPTS[v$i];"
  filter+="[$i:a]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,aformat=channel_layouts=stereo,"
  filter+="apad,atrim=duration=$seconds,asetpts=PTS-STARTPTS[a$i];"
  joined+="[v$i][a$i]"
done
filter+="${joined}concat=n=${#parts[@]}:v=1:a=1[v][a]"

partial="$out.partial.mp4"
trap 'rm -f "$partial"' EXIT
ffmpeg -v error -stats -y "${inputs[@]}" -filter_complex "$filter" -map "[v]" -map "[a]" \
  -c:v libx264 -preset medium -crf 20 -c:a aac -b:a 192k -movflags +faststart "$partial"
mv "$partial" "$out"
length="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out")"
printf 'wrote %s: %s (%.1f s; the limit is %s)\n' "$out" "$(clock "$length")" "$length" "$(clock "$max")"
