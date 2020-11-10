#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# vim:fenc=utf-8

import argparse
import json
import logging
import os
import re
import shutil
import tempfile

import coloredlogs
from nbgrader.apps import NbGraderAPI
from traitlets.config import Config
import patoolib

"""
TODOs:
    - check all return codes from nbgrader api calls
    - deal with old metadata format of submitted notebooks
    - source project config instead of implicitly setting stuff
"""


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
    patoolib.extract_archive(inputfile, outdir=target)
    extracted = []
    for root, dirs, files in os.walk(target):
        for f in filter(files):
            extracted.append(os.path.join(root, f))
        for d in filter(dirs):
            extracted.append(os.path.join(root, d))
    return extracted


def validate(submission, notebook):
    errors = []
    print(notebook)
    with open(notebook) as f:
        json_notebook = json.load(f)
        for index, cell in enumerate(json_notebook["cells"]):
            if cell['cell_type'] != 'code':
                continue # and hope for the best :-]
            lineno = 0
            for line in cell['source']:
                lineno += 1
                if (line[0].strip() == "!") or (line[0].strip() == "%"):
                    e = ("validate(%s, %s):\n"
                         "\tShell command found in cell %d, line %d:\n"
                         "\t> %s"
                         % (submission['number'], submission['assignment'],
                            index, lineno, line.strip()))
                    errors.append(e)
    return errors


def extract_files(inputfile, submission, notebook_filename):
    filename, ext = os.path.splitext(inputfile)
    datadir = 'data'

    files = []
    errors = []

    with tempfile.TemporaryDirectory() as tmpdir:
        if ext == '.ipynb':
            files.append(inputfile)
        elif ext == '.zip' or ext == '.7z':
            files.extend(extract_zip(inputfile, tmpdir))
        else:
            raise NotImplementedError

        for f in files:
            fname, fext = os.path.splitext(f)
            logging.debug("> %s" % f)
            if fext == '.ipynb':
                logging.debug("notebook found: %s" % f)
                if not submission['notebook']:
                    submission['notebook'] = f
                    nberrors = validate(submission, f)
                    submission['isvalid'] = not nberrors
                    if not nberrors:
                        os.makedirs(submission['dir'], exist_ok=True)
                        targetfile = os.path.join(submission['dir'],
                                                  notebook_filename)
                    else:
                        targetfile = os.path.join('dangerous',
                                                  submission['number'] + '-' +
                                                  notebook_filename)
                        errors.extend(nberrors)
                    shutil.copyfile(f, targetfile)
                else:
                    e = "Multiple notebooks found in submission!"
                    errors.append("extract_files %s: %s" %
                                  (submission['number'], e))
            elif os.path.isdir(f) and os.path.basename(f) == datadir:
                logging.debug("Data dir found")
                data_target_dir = os.path.join(submission['dir'], datadir)
                os.makedirs(submission['dir'], exist_ok=True)
                if os.path.exists(data_target_dir):
                    shutil.rmtree(data_target_dir)
                shutil.copytree(f, data_target_dir)

        if not submission['notebook']:
            e = "No notebook found in submission!"
            errors.append("extract_files %s: %s" % (submission['number'], e))

    return files, errors


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
    errors = []

    gre = Re()
    if gre.match(pattern_student, basename) or \
       gre.match(pattern_group, basename):
        submission = {}
        submission['assignment'] = assignment
        submission['notebook'] = None

        if gre.last_match.group('type') == 'h':
            submission['type'] = 'student'
            submission['number'] = gre.last_match.group('number')
        else:
            submission['type'] = 'group'
            submission['number'] = 'group' + gre.last_match.group('number')

        submission['dir'] = os.path.join(target, submission['number'],
                                         assignment)

        logging.info("%s submission found: %s" % (submission['type'],
                                                  basename))

        files, suberrors = extract_files(inputfile, submission,
                                         notebook_filename)
        submissions.append(submission)
        errors.extend(suberrors)
    else:
        if ext == '.ipynb':
            logging.fatal("Unmatched notebook found in %s" % inputfile)
        elif ext in ['.zip', '.7z', '.tar.gz', 'tar.bz2', 'tar.xz']:
            with tempfile.TemporaryDirectory() as tmpdir:
                logging.info("Extracting %s to %s" % (inputfile, tmpdir))
                for f in extract_zip(inputfile, tmpdir):
                    innersubs, innererrors = collect(f, target,
                                                     assignment,
                                                     notebook_filename)
                    submissions.extend(innersubs)
                    errors.extend(innererrors)
        else:
            logging.fatal("Don't know what to do with file: %s" % inputfile)
            raise NotImplementedError

    return submissions, errors


def setup():
    config = Config()
    config.Exchange.root = "/tmp/exchange"
    config.CourseDirectory.submitted_directory = 'submitted'
    config.CourseDirectory.course_id = 'example_course'
    return NbGraderAPI(config=config)


def autograde(api, assignment, submissions, force):
    errors = []
    for submission in submissions:
        if not submission['isvalid']:
            continue
        student = submission['number']
        result = api.autograde(assignment, student, force=force)
        if not result['success']:
            logging.fatal(result['log'])
            errors.append("autograde(%s, %s): Errors from nbgrader (scroll up)"
                          % (student, assignment))

    return api.get_autograded_students(assignment), errors


def formgrade():
    print()
    logging.warning("Formgrading must be done manually in a jupyter instance!")
    logging.warning("Run `jupyter notebook --no-browser` and grade manually.")

    input("Press Enter to continue when you are done formgrading\n"
          "or Ctrl-c to abort without generating feedback...")


def generate_feedback(api, assignment, student, force):
    api.generate_feedback(assignment, student, force)
    api.release_feedback(assignment, student)


def collect_feedback(api, assignment, student, output, notebook_filename):
    feedbackdir = 'feedback'
    html = os.path.join(feedbackdir, student, assignment,
                        os.path.splitext(notebook_filename)[0] + '.html')

    if os.path.exists(html):
        target = os.path.join(output, student + '.html')
        logging.info("Collecting feedback from: %s" % html)
        shutil.copy(html, target)
        return 1

    return 0


def main():
    coloredlogs.install(fmt='%(levelname)s %(message)s')
    coloredlogs.set_level(logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--assignment',
                        help='Name of the assignment',
                        type=str,
                        required=True)
    parser.add_argument('-f', '--force',
                        help='Pass --force to autograde',
                        action="store_true")
    parser.add_argument('-n', '--noop',
                        help='Do not run autograde and feedback',
                        action="store_true")
    parser.add_argument('-o', '--output',
                        help='Output directory for html feedback',
                        type=str,
                        default='upload')
    parser.add_argument('-s', '--submissiondir',
                        help='Submission directory',
                        type=str,
                        default='submitted')

    parser.add_argument('inputfiles', default=[], nargs='+')
    args = parser.parse_args()

    assignment = args.assignment
    output = os.path.join(args.output, assignment)
    api = setup()
    notebook_filename = get_notebook_name(api, assignment)
    os.makedirs('dangerous', exist_ok=True)
    submissions = []
    errors = []

    for inputfile in args.inputfiles:
        submissions, inputerrors = collect(inputfile, args.submissiondir,
                                           assignment, notebook_filename)
        errors.extend(inputerrors)

        if submissions:
            logging.info("Found %i submissions" % len(submissions))
        else:
            logging.fatal("No submissions found.")

    if args.noop:
        logging.info("-n was specified, exiting")
        exit(0)

    autograded, autograde_errors = autograde(api, assignment, submissions,
                                             args.force)
    errors.extend(autograde_errors)
    logging.info("%d submissions have been autograded" % len(autograded))
    if errors:
        logging.fatal("There were %d fatal errors during autograding:" %
                      len(errors))
        for i, e in enumerate(errors):
            logging.fatal("[%d] %s" % (i, e))

    formgrade()

    os.makedirs(output, exist_ok=True)
    reports = 0
    for student in autograded:
        generate_feedback(api, assignment, student, True)
        reports += collect_feedback(api, assignment, student, output,
                                    notebook_filename)

    logging.info("%d reports written to %s" % (reports, output))


if __name__ == "__main__":
    main()
