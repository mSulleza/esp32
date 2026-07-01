#!/usr/bin/env bash
# Headless place + route pipeline (free/open-source). Proven on KiCad 10.0.4 +
# Temurin JRE 25 + Freerouting 2.2.4. See ../LAYOUT_AUTOMATION.md.
#
# Layout of the (gitignored) toolchain it expects:
#   $TOOLS/freerouting.jar
#   $TOOLS/jdk-25*/bin/java.exe
# Get them with:
#   curl -L -o freerouting.jar https://github.com/freerouting/freerouting/releases/download/v2.2.4/freerouting-2.2.4.jar
#   curl -L -o jre.zip "https://api.adoptium.net/v3/binary/latest/25/ga/windows/x64/jre/hotspot/normal/eclipse?project=jdk"
set -euo pipefail

W="${1:?usage: run_pipeline.sh <work_dir_windows_path_as_/mnt/c/...> <netlist.net>}"   # e.g. /mnt/c/Users/you/aclayout
NET="${2:?need netlist path}"
WIN="$(printf '%s' "$W" | sed 's#/mnt/c/#C:\\\\#; s#/#\\\\#g')"                          # /mnt/c/.. -> C:\..
KICAD="/mnt/c/Program Files/KiCad/10.0/bin"
PYEXE="$KICAD/python.exe"; CLI="$KICAD/kicad-cli.exe"
JAVA="$(find "$W/tools" -iname java.exe | head -1)"; JAR="$W/tools/freerouting.jar"
MP="${MP:-30}"

cp build_board.py "$NET" "$W/" 2>/dev/null || true

echo "1) place + net  ->  placed.kicad_pcb"
"$PYEXE" "$W/build_board.py" "$WIN\\$(basename "$NET")" "$WIN\\placed.kicad_pcb"

echo "2) export Specctra DSN  (pcbnew ExportSpecctraDSN — kicad-cli can't)"
"$PYEXE" -c "import pcbnew;b=pcbnew.LoadBoard(r'$WIN\\placed.kicad_pcb');assert pcbnew.ExportSpecctraDSN(b,r'$WIN\\placed.dsn')"

echo "3) autoroute  (Freerouting headless, -mp $MP)"
"$JAVA" -jar "$JAR" --gui.enabled=false -de "$WIN\\placed.dsn" -do "$WIN\\placed.ses" -mp "$MP" 2>&1 \
  | grep -i 'session completed' | grep -iv analytics || true

echo "4) import SES  ->  routed.kicad_pcb"
"$PYEXE" -c "import pcbnew;b=pcbnew.LoadBoard(r'$WIN\\placed.kicad_pcb');assert pcbnew.ImportSpecctraSES(b,r'$WIN\\placed.ses');pcbnew.SaveBoard(r'$WIN\\routed.kicad_pcb',b)"

echo "5) DRC  (KiCad's real engine — Freerouting's is not trustworthy)"
"$CLI" pcb drc --format json --output "$W/drc.json" "$W/routed.kicad_pcb" | tail -1
echo "Open routed.kicad_pcb in KiCad to finish: refill GND zones, fix DRC, hand-route the antenna keepout + USB diff pair, complete any unrouted nets."
