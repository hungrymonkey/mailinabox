# -*- indent-tabs-mode: t; tab-width: 4; -*-

# load useful functions from setup
. ../setup/functions.sh || exit 1
. ../setup/functions-ldap.sh || exit 1
set +eu

# load test suite helper functions
. suites/_ldap-functions.sh || exit 1
. suites/_mail-functions.sh || exit 1
. suites/_mgmt-functions.sh || exit 1

# globals - all global variables are UPPERCASE
BASE_OUTPUTDIR="out"
PYMAIL="./test_mail.py"
declare -i OVERALL_SUCCESSES=0
declare -i OVERALL_FAILURES=0
declare -i OVERALL_COUNT=0
declare -i OVERALL_COUNT_SUITES=0

# ansi escapes for hilighting text
F_DANGER=$(echo -e "\033[31m")
F_WARN=$(echo -e "\033[93m")
F_RESET=$(echo -e "\033[39m")

# options
FAILURE_IS_FATAL=no


suite_start() {
	let TEST_NUM=1
	let SUITE_COUNT_SUCCESS=0
	let SUITE_COUNT_FAILURE=0
	let SUITE_COUNT_TOTAL=0
	SUITE_NAME="$1"
	OUTDIR="$BASE_OUTPUTDIR/$SUITE_NAME"
	mkdir -p "$OUTDIR"
	echo ""
	echo "Starting suite: $SUITE_NAME"
	suite_setup "$2"
}

suite_end() {
	suite_cleanup "$1"
	echo "Suite $SUITE_NAME finished"
	let OVERALL_SUCCESSES+=$SUITE_COUNT_SUCCESS
	let OVERALL_FAILURES+=$SUITE_COUNT_FAILURE
	let OVERALL_COUNT+=$SUITE_COUNT_TOTAL
	let OVERALL_COUNT_SUITES+=1
}

suite_setup() {
	[ -z "$1" ] && return 0
	TEST_OF="$OUTDIR/setup"
	eval "$1"
	TEST_OF=""
}

suite_cleanup() {
	[ -z "$1" ] && return 0
	TEST_OF="$OUTDIR/cleanup"
	eval "$1"
	TEST_OF=""
}

test_start() {
	TEST_DESC="${1:-}"
	TEST_NAME="$(printf "%03d" $TEST_NUM)"
	TEST_OF="$OUTDIR/$TEST_NAME"
	TEST_STATE=""
	TEST_STATE_MSG=()
	echo "TEST-START \"${TEST_DESC:-unnamed}\"" >$TEST_OF
	echo -n "  $TEST_NAME: $TEST_DESC: "
	let TEST_NUM+=1
	let SUITE_COUNT_TOTAL+=1
}

test_end() {
	[ -z "$TEST_OF" ] && return
	if [ $# -gt 0 ]; then
		[ -z "$1" ] && test_success || test_failure "$1"
	fi
	case $TEST_STATE in
		SUCCESS | "" )
			record "[SUCCESS]"
			echo "SUCCESS"
			let SUITE_COUNT_SUCCESS+=1
			;;
		FAILURE )
			record "[FAILURE]"
			echo "${F_DANGER}FAILURE${F_RESET}:"
			local idx=0
			while [ $idx -lt ${#TEST_STATE_MSG[*]} ]; do
				record "${TEST_STATE_MSG[$idx]}"
				echo "	   why: ${TEST_STATE_MSG[$idx]}"
				let idx+=1
			done
			echo "	   see: $(dirname $0)/$TEST_OF"
			let SUITE_COUNT_FAILURE+=1
			if [ "$FAILURE_IS_FATAL" == "yes" ]; then
				record "FATAL: failures are fatal option enabled"
				echo "FATAL: failures are fatal option enabled"
				exit 1
			fi
			;;
		* )
			record "[INVALID TEST STATE '$TEST_STATE']"
			echo "Invalid TEST_STATE=$TEST_STATE"
			let SUITE_COUNT_FAILURE+=1
			;;
	esac
	TEST_OF=""
}

test_success() {
	[ -z "$TEST_OF" ] && return
	[ -z "$TEST_STATE" ] && TEST_STATE="SUCCESS"
}

test_failure() {
	local why="$1"
	[ -z "$TEST_OF" ] && return
	TEST_STATE="FAILURE"
	TEST_STATE_MSG+=( "$why" )
}

have_test_failures() {
	[ "$TEST_STATE" == "FAILURE" ] && return 0
	return 1
}

record() {
	if [ ! -z "$TEST_OF" ]; then
		echo "$@" >>$TEST_OF
	else
		echo "$@"
	fi
}

die() {
	record "FATAL: $@"
	test_failure "a fatal error occurred"
	test_end
	echo "FATAL: $@"
	exit 1
}

array_contains() {
	local searchfor="$1"
	shift
	local item
	for item; do
		[ "$item" == "$searchfor" ] && return 0
	done
	return 1
}

python_error() {
	# finds tracebacks and outputs just the final error message of
	# each
	local output="$1"
	awk 'BEGIN { TB=0; FOUND=0 } TB==0 && /^Traceback/ { TB=1; FOUND=1; next } TB==1 && /^[^ ]/ { print $0; TB=0 } END { if (FOUND==0) exit 1 }' <<< "$output"
	[ $? -eq 1 ] && echo "$output"
}



##
## Initialize
##

mkdir -p "$BASE_OUTPUTDIR"

# load global vars
. /etc/mailinabox.conf || die "Could not load '/etc/mailinabox.conf'"
. "${STORAGE_ROOT}/ldap/miab_ldap.conf" || die "Could not load miab_ldap.conf"
