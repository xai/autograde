#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# vim:fenc=utf-8

import argparse
import logging
import os
import re
import shutil
import tempfile
import zipfile

import coloredlogs
from nbgrader.apps import NbGraderAPI
from traitlets.config import Config
import py7zr


class Re(object):

    def __init__(self):
        self.last_match = None

    def match(self, pattern, text):
        self.last_match = re.match(pattern, text)
        return self.last_match

    def search(self, pattern, text):
        self.last_match = re.search(pattern, text)
        return self.last_match


def get_notebook_name(api, assignment):
    notebooks = api.get_notebooks(assignment)

    if not notebooks:
        logging.fatal("No source notebooks found for assignment")
        raise RuntimeError

    return notebooks[0]['name'] + ".ipynb"


def filter(items):
    return [i for i in items if not i.startswith('__MACOSX/')
            and not i.startswith('.')
            and not os.path.basename(i).startswith('.')]


def extract_zip(inputfile, target):
    filename, ext = os.path.splitext(inputfile)
    extracted = []

    if ext == '.zip':
        with zipfile.ZipFile(inputfile, 'r') as zipFile:
            for item in filter(zipFile.namelist()):
                zipFile.extract(item, path=target)
                extracted.append(item)

    elif ext == '.7z':
        with py7zr.SevenZipFile(inputfile, 'r') as zipFile:

            for item in filter(zipFile.getnames()):
                zipFile.extract(path=target, targets=item)
                extracted.append(item)
    else:
        raise NotImplementedError

    return [os.path.join(target, f) for f in extracted]


def extract_files(inputfile, target, submission, notebook_filename):
    filename, ext = os.path.splitext(inputfile)
    data_filename = 'data'

    notebook = None
    files = []

    with tempfile.TemporaryDirectory() as tmpdir:
        if ext == '.ipynb':
            files.append(inputfile)
        elif ext == '.zip' or ext == '.7z':
            files.extend(extract_zip(inputfile, tmpdir))
        else:
            raise NotImplementedError

        for f in files:
            fname, fext = os.path.splitext(f)
            if fext == '.ipynb':
                if not notebook:
                    notebook = f
                    shutil.copyfile(notebook,
                                    os.path.join(submission['dir'],
                                                 notebook_filename))
                else:
                    logging.warning("Multiple notebooks found in submission!")
            elif f == data_filename:
                shutil.copy(f, os.path.join(submission['dir'],
                                            data_filename))

        if not notebook:
            logging.warning("No notebook found in submission!")

    return files


def collect(inputfile, target, assignment, notebook_filename):
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

        if gre.last_match.group('type') == 'h':
            submission['type'] = 'student'
            submission['number'] = gre.last_match.group('number')
        else:
            submission['type'] = 'group'
            submission['number'] = 'group' + gre.last_match.group('number')

        submission['dir'] = os.path.join(target, submission['number'],
                                         assignment)
        os.makedirs(submission['dir'], exist_ok=True)

        logging.info("%s submission found: %s" % (submission['type'],
                                                  basename))

        extract_files(inputfile, target, submission, notebook_filename)

        submissions.append(submission)
    else:
        if ext == '.ipynb':
            logging.warning("Unmatched notebook found in %s" % inputfile)
        elif ext == '.zip' or ext == '.7z':
            with tempfile.TemporaryDirectory() as tmpdir:
                logging.info("Extracting %s to %s" % (inputfile, tmpdir))
                for f in extract_zip(inputfile, tmpdir):
                    submissions.extend(collect(f, target,
                                               assignment,
                                               notebook_filename))
        else:
            logging.warning("Don't know what to do with file: %s" % inputfile)
            raise NotImplementedError

    return submissions


def setup():
    config = Config()
    config.Exchange.root = "/tmp/exchange"
    config.CourseDirectory.submitted_directory = 'submitted'
    config.CourseDirectory.course_id = 'example_course'
    return NbGraderAPI(config=config)


def autograde(api, assignment, force):
    for student in api.get_submitted_students(assignment):
        api.autograde(assignment, student, force=force)

    return api.get_autograded_students(assignment)


def formgrade():
    logging.warning("Formgrading must be done manually in a jupyter instance!")
    logging.warning("Run `jupyter notebook --no-browser` and grade manually.")

    input("Press Enter to continue when you are done grading ...")


def generate_feedback(api, assignment, student, force):
    api.generate_feedback(assignment, student, force)


def main():
    logging.basicConfig(level=logging.DEBUG)
    # coloredlogs.install(fmt='%(asctime)s %(levelname)s %(message)s')
    coloredlogs.install(fmt='%(levelname)s %(message)s')

    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--assignment',
                        help='Name of the assignment',
                        type=str,
                        required=True)
    parser.add_argument('-f', '--force',
                        help='Pass --force to autograde',
                        action="store_true")
    parser.add_argument('-o', '--output',
                        help='Output directory',
                        type=str,
                        default='submitted')

    parser.add_argument('inputfiles', default=[], nargs='+')
    args = parser.parse_args()

    assignment = args.assignment
    api = setup()
    notebook_filename = get_notebook_name(api, assignment)

    for inputfile in args.inputfiles:
        submissions = collect(inputfile, args.output, assignment,
                              notebook_filename)

        if submissions:
            logging.info("Found %i submissions" % len(submissions))
        else:
            logging.warning("No submissions found.")

    autograded = autograde(api, assignment, args.force)
    logging.info("%d submissions have been autograded" % len(autograded))

    formgrade()

    for student in autograded:
        generate_feedback(api, assignment, student, True)


if __name__ == "__main__":
    main()
