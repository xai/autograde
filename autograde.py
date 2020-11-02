#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# vim:fenc=utf-8

import argparse
import os
import re
import shutil
import tempfile
import zipfile

from plumbum.colors import warn
from plumbum.colors import info
from plumbum.colors import success
# from plumbum import local
# from plumbum.commands.processes import ProcessExecutionError


class Re(object):

    def __init__(self):
        self.last_match = None

    def match(self, pattern, text):
        self.last_match = re.match(pattern, text)
        return self.last_match

    def search(self, pattern, text):
        self.last_match = re.search(pattern, text)
        return self.last_match


def extract_zip(inputfile, target):
    filename, ext = os.path.splitext(inputfile)

    assert (ext == '.zip'), "Not a .zip file!"
    
    with zipfile.ZipFile(inputfile, 'r') as zipFile:
        extracted = []
        for item in zipFile.infolist():
            # exclude hidden directories (that have likely been inserted
            # accidentally
            if not str(item.filename).startswith('__MACOSX/') and \
               not str(item.filename).startswith('.') and \
               not os.path.basename(str(item.filename)).startswith('.'):
                zipFile.extract(item, path=target)
                extracted.append(str(item.filename))

        return [os.path.join(target, f) for f in extracted]


def extract_files(inputfile, target, submission):
    filename, ext = os.path.splitext(inputfile)
    basename = os.path.basename(inputfile)
    notebook_filename = 'notebook-1.ipynb'
    data_filename = 'data'

    notebook = None
    files = []

    with tempfile.TemporaryDirectory() as tmpdir:
        if ext == '.ipynb':
            files.append(inputfile)
        elif ext == '.zip':
            files.extend(extract_zip(inputfile, tmpdir))

        for f in files:
            fname, fext = os.path.splitext(f)
            if fext == '.ipynb':
                if not notebook:
                    notebook = f
                    shutil.copyfile(notebook,
                                    os.path.join(submission['dir'],
                                                 notebook_filename))
                else:
                    print(warn | ("More than one notebooks found in"
                                  "submission"))
            elif f == data_filename:
                shutil.copy(f, os.path.join(submission['dir'],
                                            data_filename))

        if not notebook:
            print(warn | "No notebook found in submission!")

    return files


def prepare_submissions(inputfile, target, assignment):
    submissions = []
    pattern_student = (rf"^(?P<type>h)(?P<number>[0-9]+)_"
                       rf"(?P<firstname>[^_]+)_"
                       rf"(?P<lastname>[^_]+)_"
                       rf"(?P<filename>.+)")
    pattern_group = (rf"^(?P<type>Gruppe|Group) (?P<number>[0-9]+)_"
                     rf"(?P<firstname>[^_]*)_?"
                     rf"(?P<lastname>[^_]*)_"
                     rf"(?P<filename>.+)")
    filename, ext = os.path.splitext(inputfile)
    basename = os.path.basename(inputfile)

    gre = Re()
    if gre.match(pattern_student, basename) or \
       gre.match(pattern_group, basename):
        submission = {}
        submission['type'] = 'student' \
                if gre.last_match.group('type') == 'h' \
                else 'group'
        submission['number'] = gre.last_match.group('number')
        submission['dir'] = os.path.join(target, submission['number'], assignment)
        os.makedirs(submission['dir'], exist_ok=True)

        print(success | ("%s submission found: %s" % (submission['type'],
                                                      basename)))

        extract_files(inputfile, target, submission)

        submissions.append(submission)
    else:
        if ext == '.ipynb':
            print(warn | ("Unmatched notebook found in %s" % inputfile))
        elif ext == '.zip':
            with tempfile.TemporaryDirectory() as tmpdir:
                print("Extracting %s to %s" % (inputfile, tmpdir))
                for f in extract_zip(inputfile, tmpdir):
                    submissions.extend(prepare_submissions(f, target,
                                                           assignment))
        else:
            print(warn | ("Don't know what to do with file: %s" % inputfile))
            raise NotImplementedError

    return submissions


def collect():
    pass


def autograde():
    pass


def formgrade():
    pass


def generate_feedback():
    pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--assignment',
                        help='Name of the assignment',
                        type=str,
                        required=True)
    parser.add_argument('-n', '--noop',
                        help='Do not actually run',
                        action="store_true")
    parser.add_argument('-o', '--output',
                        help='Output directory',
                        type=str,
                        default='submitted')
    parser.add_argument('-p', '--prefix',
                        help='Prefix string for the filenames',
                        type=str)
    parser.add_argument('inputfiles', default=[], nargs='+')
    args = parser.parse_args()

    for inputfile in args.inputfiles:
        submissions = prepare_submissions(inputfile, args.output, args.assignment)

        if submissions:
            print(success | ("Found %i submissions" % len(submissions)))
        else:
            print(warn | "No submissions found.")

    collect()
    autograde()
    formgrade()
    generate_feedback()


if __name__ == "__main__":
    main()
