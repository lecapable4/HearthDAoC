#!/usr/bin/env bash
# Runs connect-hearthdaoc.bat under Wine in a throwaway prefix with DRYRUN=1. Local only (needs wine).
set -euo pipefail
command -v wine >/dev/null || { echo "SKIP: wine not installed"; exit 0; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
T="$(mktemp -d)"; trap 'WINEPREFIX="$T/pfx" wineserver -k 2>/dev/null || true; rm -rf "$T"' EXIT
export WINEPREFIX="$T/pfx" WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml=;winemenubuilder.exe=d"
wineboot -i >/dev/null 2>&1
fail() { echo "FAIL: $*" >&2; exit 1; }
setup() { rm -rf "$T/app"; mkdir -p "$T/app"; cp "$HERE/../windows/connect-hearthdaoc.bat" "$T/app/"; : > "$T/app/connect.exe"; }

setup
printf '"SERVER=192.168.1.64:10301"\r\n"ACCOUNT=Tester1"\r\n"PASSWORD=pw1"\r\n' > "$T/app/hearthdaoc.cfg"
out="$(cd "$T/app" && DRYRUN=1 wine cmd /c connect-hearthdaoc.bat 2>/dev/null | tr -d '\r')"
grep -qF 'connect.exe game.dll "192.168.1.64:10301" "Tester1" "pw1"' <<<"$out" || fail "saved settings: got: $out"
echo "ok - connect-hearthdaoc.bat builds the connect.exe command from hearthdaoc.cfg"

# First run: the answers are saved; cmd metacharacters in the password must survive saving and loading.
setup
# (Not % : Wine's cmd re-expands percent signs inside values, which real cmd does not; players are told to avoid it.)
pw='p&w|x<y>^z!)'
# (Answers come from the environment: Wine's set /p swallows the rest of piped or redirected input.)
out="$(cd "$T/app" && SERVER=192.168.1.64:10301 ACCOUNT=Tester2 PASSWORD="$pw" DRYRUN=1 wine cmd /c connect-hearthdaoc.bat 2>/dev/null | tr -d '\r')"
grep -qF "connect.exe game.dll \"192.168.1.64:10301\" \"Tester2\" \"$pw\"" <<<"$out" || fail "special password on first run: got: $out"
grep -qF "\"PASSWORD=$pw\"" <(tr -d '\r' < "$T/app/hearthdaoc.cfg") || fail "special password not saved intact: $(cat "$T/app/hearthdaoc.cfg")"
out="$(cd "$T/app" && DRYRUN=1 wine cmd /c connect-hearthdaoc.bat 2>/dev/null | tr -d '\r')"
grep -qF "\"$pw\"" <<<"$out" || fail "special password from saved settings: got: $out"
echo "ok - passwords with & | < > ^ ! ) survive saving, loading and the command line"

# The patch step: when patch-client.ps1 is next to the .bat, it runs just before connect.exe starts,
# once for each patch set in the patches folder. A stand-in powershell.cmd in the app folder (cmd
# finds it before the real one) echoes its arguments and exits with FAKE_LAYOUT_EXIT when its 7th
# argument (after -PatchSet) is default-layout.json, else with FAKE_PS_EXIT.
save_settings() { printf '"SERVER=192.168.1.64:10301"\r\n"ACCOUNT=Tester1"\r\n"PASSWORD=pw1"\r\n' > "$T/app/hearthdaoc.cfg"; }
setup_patch() {
    setup; save_settings
    : > "$T/app/patch-client.ps1"; mkdir -p "$T/app/patches"
    : > "$T/app/patches/classic-creation.json"; : > "$T/app/patches/default-layout.json"
    printf '@echo off\r\necho stand-in powershell %%*\r\nif /i "%%~nx7"=="default-layout.json" exit /b %%FAKE_LAYOUT_EXIT%%\r\nexit /b %%FAKE_PS_EXIT%%\r\n' > "$T/app/powershell.cmd"
}
run_bat() {  # run_bat <classic set's exit code> [folder]: the .bat's output; keys for its pauses come on stdin
    # LAYOUT_EXIT (default 0) is the default layout set's exit code.
    (cd "${2:-$T/app}" && FAKE_PS_EXIT="$1" FAKE_LAYOUT_EXIT="${LAYOUT_EXIT:-0}" DRYRUN=1 wine cmd /c connect-hearthdaoc.bat 2>/dev/null <<<$'\n\n' | tr -d '\r')
}
line_of() { { grep -nE -m1 -- "$1" <<<"$2" || true; } | cut -d: -f1; }  # line_of <regex> <text>: first matching line number, or nothing
PATCH_LINE='^powershell -NoProfile -ExecutionPolicy Bypass -File ".*\\app\\patch-client\.ps1"$'
STAND_IN='^stand-in powershell -NoProfile -ExecutionPolicy Bypass -File ".*\\app\\patch-client\.ps1"$'
# (Not anchored at the start: after the pause, Wine prints the next line on the same one.)
CONNECT_LINE='connect\.exe game\.dll "192\.168\.1\.64:10301" "Tester1" "pw1"$'
WARNING='^Warning: .*patch-client\.bat'
PAUSE='Press any key'
# (After the classic set's pause, Wine prints the layout's line on the pause's line.)
LAYOUT_LINE='(^|continue\.\.\. )powershell -NoProfile -ExecutionPolicy Bypass -File ".*\\app\\patch-client\.ps1" -PatchSet ".*\\app\\patches\\default-layout\.json"$'
LAYOUT_RAN='^stand-in powershell -NoProfile -ExecutionPolicy Bypass -File ".*\\app\\patch-client\.ps1" -PatchSet ".*\\app\\patches\\default-layout\.json"$'
CLASSIC_WARNING="^Warning: HearthDAoC's client patches could not be applied .*patch-client\\.bat"
LAYOUT_WARNING="^Warning: HearthDAoC's default layout could not be applied .*patch-client\\.bat"

for code in 0 3 1; do
    setup_patch
    out="$(run_bat "$code")"
    patch="$(line_of "$PATCH_LINE" "$out")"; ran="$(line_of "$STAND_IN" "$out")"; connect="$(line_of "$CONNECT_LINE" "$out")"
    [[ -n "$patch" && -n "$ran" && -n "$connect" ]] || fail "exit $code: patch line, patch run or connect line missing: got: $out"
    (( patch < ran && ran < connect )) || fail "exit $code: the patch step must come before connect.exe: got: $out"
    warning="$(line_of "$WARNING" "$out")"; pause="$(line_of "$PAUSE" "$out")"
    if [[ $code == 1 ]]; then
        [[ -n "$warning" && -n "$pause" ]] && (( ran < warning && warning < pause && pause <= connect )) ||
            fail "exit 1: no warning and pause before connect.exe: got: $out"
    else
        [[ -z "$warning$pause" ]] || fail "exit $code: unexpected warning or pause: got: $out"
    fi
done
echo "ok - connect-hearthdaoc.bat runs patch-client.ps1 before connect.exe; exit 0 and 3 go on, others warn, pause and go on"

# The default layout is a patch set of its own: it runs after the classic set whatever that one gave (a
# refused or failed set never stops the other), and before connect.exe; its failures warn on their own.
for codes in "0 0" "3 0" "1 0" "0 3" "0 1" "2 1"; do
    read -r classic layout <<<"$codes"
    setup_patch
    out="$(LAYOUT_EXIT="$layout" run_bat "$classic")"
    ran="$(line_of "$STAND_IN" "$out")"; shown="$(line_of "$LAYOUT_LINE" "$out")"; layout_ran="$(line_of "$LAYOUT_RAN" "$out")"
    connect="$(line_of "$CONNECT_LINE" "$out")"
    [[ -n "$ran" && -n "$shown" && -n "$layout_ran" && -n "$connect" ]] ||
        fail "exits $codes: a patch run, the layout line or the connect line missing: got: $out"
    (( ran < shown && shown < layout_ran && layout_ran < connect )) ||
        fail "exits $codes: the classic set, then the layout set, then connect.exe: got: $out"
    classic_warning="$(line_of "$CLASSIC_WARNING" "$out")"; layout_warning="$(line_of "$LAYOUT_WARNING" "$out")"
    if [[ $classic == [03] ]]; then
        [[ -z "$classic_warning" ]] || fail "exits $codes: unexpected classic warning: got: $out"
    else
        [[ -n "$classic_warning" ]] && (( ran < classic_warning && classic_warning < shown )) ||
            fail "exits $codes: no classic warning between the two runs: got: $out"
    fi
    if [[ $layout == [03] ]]; then
        [[ -z "$layout_warning" ]] || fail "exits $codes: unexpected layout warning: got: $out"
    else
        [[ -n "$layout_warning" ]] && (( layout_ran < layout_warning && layout_warning < connect )) ||
            fail "exits $codes: no layout warning before connect.exe: got: $out"
    fi
done
echo "ok - the default layout set runs on its own after the classic one, whatever that one gave, and warns on its own"

# A player who restored a set and deleted its file keeps the game's own: no patch run for it.
setup_patch
rm "$T/app/patches/default-layout.json"
out="$(LAYOUT_EXIT=1 run_bat 0)"
[[ -n "$(line_of "$STAND_IN" "$out")" && -n "$(line_of "$CONNECT_LINE" "$out")" ]] || fail "without default-layout.json: got: $out"
[[ -z "$(line_of 'default-layout' "$out")" ]] || fail "without default-layout.json: a layout run: got: $out"
setup_patch
rm "$T/app/patches/classic-creation.json"
out="$(run_bat 1)"
[[ -n "$(line_of "$LAYOUT_RAN" "$out")" && -n "$(line_of "$CONNECT_LINE" "$out")" ]] || fail "without classic-creation.json: got: $out"
[[ -z "$(line_of "$STAND_IN" "$out")$(line_of "$WARNING" "$out")" ]] || fail "without classic-creation.json: a classic run: got: $out"
echo "ok - without one patch set's file, only the other one runs"

# The folder name reaches powershell as it is, cmd's special characters included (not %: see above).
setup_patch
odd="$T/odd & dir ^1 (x)!"
rm -rf "$odd"; cp -r "$T/app" "$odd"
out="$(run_bat 0 "$odd")"
grep -F 'stand-in powershell -NoProfile -ExecutionPolicy Bypass -File "' <<<"$out" |
    grep -qF '\odd & dir ^1 (x)!\patch-client.ps1"' || fail "folder with & ^ ( ) !: got: $out"
[[ -n "$(line_of "$CONNECT_LINE" "$out")" ]] || fail "folder with & ^ ( ) !: no connect line: got: $out"
echo "ok - the patch step works in a folder whose name has & ^ ( ) !"

setup_patch
rm "$T/app/patch-client.ps1"
out="$(run_bat 1)"
[[ -n "$(line_of "$CONNECT_LINE" "$out")" ]] || fail "without patch-client.ps1: no connect line: got: $out"
! grep -qi 'powershell' <<<"$out" || fail "without patch-client.ps1: a patch step ran: got: $out"

# Without the patch set (a player who deleted the patches folder to opt out), there is no patch step either.
setup_patch
rm -r "$T/app/patches"
out="$(run_bat 1)"
[[ -n "$(line_of "$CONNECT_LINE" "$out")" ]] || fail "without the patches folder: no connect line: got: $out"
! grep -qi 'powershell' <<<"$out" || fail "without the patches folder: a patch step ran: got: $out"
echo "ok - without patch-client.ps1, or without the patches folder, there is no patch step"

# patch-client.bat runs patch-client.ps1 once for each patch set (both with the player's options), or once
# for the one -PatchSet names, and exits with the first failed run's code. Its window pauses: it was
# started by name, as from Explorer.
run_patch_bat() {  # run_patch_bat <classic exit> <layout exit> [args...]: its output, then "exit <code>"
    local classic="$1" layout="$2"; shift 2
    (cd "$T/app" && FAKE_PS_EXIT="$classic" FAKE_LAYOUT_EXIT="$layout" wine cmd /c patch-client.bat "$@" 2>/dev/null <<<$'\n' | tr -d '\r'
     echo "exit ${PIPESTATUS[0]}")
}
PS1_CALL='^stand-in powershell -NoProfile -ExecutionPolicy Bypass -File "[^"]*\\app\\patch-client\.ps1"'
CLASSIC_SET=' -PatchSet "[^"]*\\app\\patches\\classic-creation\.json"'
LAYOUT_SET=' -PatchSet "[^"]*\\app\\patches\\default-layout\.json"'
setup_patch; cp "$HERE/../windows/patch-client.bat" "$T/app/"
out="$(run_patch_bat 0 0)"
classic="$(line_of "$PS1_CALL$CLASSIC_SET ?\$" "$out")"; layout="$(line_of "$PS1_CALL$LAYOUT_SET ?\$" "$out")"
[[ -n "$classic" && -n "$layout" ]] && (( classic < layout )) || fail "patch-client.bat: the classic set, then the layout set: got: $out"
grep -qx 'exit 0' <<<"$out" || fail "patch-client.bat: exit 0 expected: got: $out"
out="$(run_patch_bat 0 0 -Restore)"
[[ -n "$(line_of "$PS1_CALL$CLASSIC_SET -Restore\$" "$out")" && -n "$(line_of "$PS1_CALL$LAYOUT_SET -Restore\$" "$out")" ]] ||
    fail "patch-client.bat -Restore: both sets, with -Restore: got: $out"
out="$(run_patch_bat 0 0 -PatchSet 'patches\default-layout.json' -Restore)"
[[ "$(grep -c '^stand-in powershell' <<<"$out")" == 1 && -n "$(line_of "$PS1_CALL -PatchSet patches.default-layout\.json -Restore\$" "$out")" ]] ||
    fail "patch-client.bat -PatchSet: one run, with the player's options: got: $out"
for codes in "3 0 3" "0 1 1" "2 1 2" "0 3 3"; do
    read -r classic layout expected <<<"$codes"
    out="$(run_patch_bat "$classic" "$layout")"
    [[ "$(grep -c '^stand-in powershell' <<<"$out")" == 2 ]] || fail "patch-client.bat, exits $classic $layout: both sets run: got: $out"
    grep -qx "exit $expected" <<<"$out" || fail "patch-client.bat, exits $classic $layout: exit $expected expected: got: $out"
done
rm -r "$T/app/patches"
out="$(run_patch_bat 2 2)"
[[ "$(grep -c '^stand-in powershell' <<<"$out")" == 1 && -n "$(line_of "$PS1_CALL ?\$" "$out")" ]] ||
    fail "patch-client.bat without the patches folder: one run, without -PatchSet: got: $out"
grep -qx 'exit 2' <<<"$out" || fail "patch-client.bat without the patches folder: its exit code: got: $out"
setup_patch; cp "$HERE/../windows/patch-client.bat" "$T/app/"
rm -rf "$odd"; cp -r "$T/app" "$odd"
out="$(cd "$odd" && FAKE_PS_EXIT=0 FAKE_LAYOUT_EXIT=0 wine cmd /c patch-client.bat 2>/dev/null <<<$'\n' | tr -d '\r')"
for set in classic-creation default-layout; do
    grep -F '\odd & dir ^1 (x)!\patch-client.ps1" -PatchSet "' <<<"$out" | grep -qF "\\odd & dir ^1 (x)!\\patches\\$set.json\"" ||
        fail "patch-client.bat in a folder with & ^ ( ) !: no $set run: got: $out"
done
echo "ok - patch-client.bat runs each patch set on its own, or the one -PatchSet names, with the first failure's exit code"
