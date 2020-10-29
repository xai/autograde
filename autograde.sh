#!/usr/bin/env bash

set -eu

DEBUG=0
CONFIG="nbgrader_config.py"
SOURCE="source"
FEEDBACK="feedback"

usage() { echo "Usage: $0 -a <assignment string> [-n <notebooks dir>] [-p <prefix string>] <zip file>" 1>&2; exit 1; }

debug() {
	if [ $DEBUG == 1 ]
	then
		echo "[DEBUG] $@"
	fi
}

while getopts "a:n:o:p:" opt; do
	case "${opt}" in
		a)
			assignment=${OPTARG}
			;;
		n)
			notebooks=${OPTARG}
			;;
		o)
			output=${OPTARG}
			;;
		p)
			prefix=${OPTARG}
			;;
		*)
			usage
			;;
	esac
done

shift $(expr $OPTIND - 1)

if [ -z "${1:-}" ] || [ -z "${assignment:-}" ]
then
	usage
else
	if [ ! -f "$1" ]
	then
		echo "Error: Not a file: $1" 1>&2; exit 2
	else
		input="$(realpath -e "$1")"
	fi
fi

: ${notebooks:="downloaded/${assignment}/archive"}
: ${output:="$FEEDBACK"}
: ${prefix:=""}

source_file=${SOURCE}/${assignment}
if [ ! -d $source_file ]
then
	echo "Error: source file of assignment not found: ${source_file}" 1>&2; exit 3
fi

file_id=$(basename $(find ${source_file} -name \*.ipynb | head -n1) .ipynb)

mkdir -p $notebooks
pushd . >/dev/null
cd $notebooks

debug "unzip $input"
unzip "$input"

# fix filenames of notebooks
SAVEIFS=$IFS
IFS=$'\n'
for i in $(zipinfo -1 "$input")
do
	[ -f "$i" ] && debug 
	group=$(echo "$i" | sed 's/^Gruppe \([0-9]\+\)__.*/\1/')
	extension=$(echo "$i" | rev | cut -d'.' -f1 | rev)
	debug "Found assignment for group $group in $i"
	newfilename="${prefix}_group${group}_${file_id}.${extension}"
	debug "move to $newfilename"
	mv "${i}" $newfilename
done
IFS=$SAVEIFS

if [ ! -f $CONFIG ]
then
	cat <<EOF > $CONFIG
c = get_config()

# Only set for demo purposes so as to not mess up the other documentation
c.CourseDirectory.submitted_directory = 'submitted_zip'
c.CourseDirectory.course_id = 'example_course'
c.Exchange.root = "/tmp/exchange"

# Only collect submitted notebooks with valid names
c.ZipCollectApp.strict = True

# Apply this regular expression to the extracted file filename (absolute path)
c.FileNameCollectorPlugin.named_regexp = (
    '.*_(?P<student_id>\w+)_'
    '(?P<file_id>.*)'
)
EOF
fi

popd > /dev/null

nbgrader zip_collect ${assignment} && \
nbgrader autograde ${assignment}

if [ $? != 0 ]
then
	echo 'There were errors! Not proceeding.' 1>&2
	exit 4
fi

echo
read -p "Start formgrading? " -r
if [[ $REPLY =~ ^[Yy]$ ]]
then
	# `nbgrader formgrade` has been deprecated :(
	echo 'Starting jupyter notebook.'
	echo 'Please use the formgrader tab for manual grading!'
	echo "Abort with Ctrl-c when you're done."
	jupyter notebook --no-browser
fi

echo
read -p "Generate feedback? " -r
if [[ $REPLY =~ ^[Yy]$ ]]
then
	nbgrader generate_feedback ${assignment}

	# flatten hierarchy for easier uploading
	pushd . >/dev/null
	mkdir -p $output
	cd $output
	find * -type f -name \*.html | while read line
	do
		cp $line $(echo "$line" | tr '/' '-')
	done
	popd > /dev/null

	echo
	echo "Feedback generated:"
	ls ${output}/*.html
fi
