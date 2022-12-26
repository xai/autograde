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
from traitlets.config import get_config
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


class Validator:

    def __init__(self, warn_only=False):
        self.warn_only = warn_only

    def validate(self, submission, notebook):
        raise NotImplementedError

    def is_warn_only(self):
        return self.warn_only


class IllegalStuffValidator(Validator):

    def __init__(self, warn_only=False):
        super().__init__(warn_only)

    def validate(self, submission, notebook):
        violations = []
        with open(notebook) as f:
            json_notebook = json.load(f)
            for index, cell in enumerate(json_notebook["cells"]):
                if cell['cell_type'] != 'code':
                    continue  # and hope for the best :-]
                lineno = 0
                for line in cell['source']:
                    lineno += 1
                    violation = None
                    if (line[0].strip() == "!"):
                        violation = "Shell command"
                    if (line[0].strip() == "%"):
                        violation = "Built-in magic command"

                    if violation:
                        e = ("validate(%s, %s):\n"
                             "\t%s found in cell %d, line %d:\n"
                             "\t> %s"
                             % (submission['number'], submission['assignment'],
                                violation, index, lineno, line.strip()))
                        violations.append(e)
        return violations


class Collector:

    def __init__(self, api, assignment, notebook_filename, datadir=["data"]):
        self.api = api
        self.assignment = assignment
        self.notebook_filename = notebook_filename
        self.datadir = datadir
        self.dangerous_dir = "dangerous"
        self.validators = []
        self.interactive = False

    def register_validator(self, validator):
        if validator not in self.validators:
            self.validators.append(validator)

    def unregister_validator(self, validator):
        if validator in self.validators:
            self.validators.remove(validator)

    def set_data_dir(self, datadir):
        self.datadir = datadir

    def set_dangerous_dir(self, dangerous_dir):
        os.makedirs(dangerous_dir, exist_ok=True)
        self.dangerous_dir = dangerous_dir

    def set_interactive(self, interactive):
        self.interactive = interactive

    def collect_submissions(self, inputfile, target):
        submissions = []
        pattern_student = (rf"^(?P<number>[0-9]{8})_"
                           rf"(?P<firstname>[^_]+)_"
                           rf"(?P<lastname>[^_]+)_"
                           rf"(?P<filename>.+)")
        pattern_group = (rf"^(?P<isgroup>Gruppe|Group) (?P<number>[0-9]+)_"
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
            submission['assignment'] = self.assignment
            submission['notebook'] = None
            submission['datadir'] = None

            if 'isgroup' not in gre.last_match.groupdict():
                submission['type'] = 'student'
                submission['number'] = gre.last_match.group('number')
            else:
                submission['type'] = 'group'
                submission['number'] = 'group' + gre.last_match.group('number')

            submission['dir'] = os.path.join(target, submission['number'],
                                             self.assignment)

            logging.info("%s submission found: %s" % (submission['type'],
                                                      basename))

            files, suberrors = self.collect_files(inputfile, submission)
            submissions.append(submission)
            errors.extend(suberrors)
        else:
            if ext == '.ipynb':
                e = ("Unmatched notebook found in %s" % inputfile)
                errors.append(e)
                logging.fatal(e)
            elif ext in ['.zip', '.7z', '.tar.gz', 'tar.bz2', 'tar.xz']:
                # look for submission inside archive
                with tempfile.TemporaryDirectory() as tmpdir:
                    logging.info("Extracting %s to %s" % (inputfile, tmpdir))
                    for f in self.extract_zip(inputfile, tmpdir):
                        innersubs, innererrors = \
                                self.collect_submissions(f, target)
                        submissions.extend(innersubs)
                        errors.extend(innererrors)
            else:
                logging.fatal("Don't know what to do with file: %s" %
                              inputfile)
                raise NotImplementedError

        return submissions, errors

    def collect_files(self, inputfile, submission):
        submission['invalid'] = False
        filename, ext = os.path.splitext(inputfile)

        files = []
        errors = []

        with tempfile.TemporaryDirectory() as tmpdir:
            if ext == '.ipynb':
                files.append(inputfile)
            elif ext in ['.rar', '.zip', '.7z']:
                files.extend(self.extract_zip(inputfile, tmpdir))
            else:
                raise NotImplementedError

            for f in files:
                fname, fext = os.path.splitext(f)
                logging.debug("> %s" % f)
                if fext == '.ipynb':
                    logging.debug("notebook found: %s" % f)
                    if not submission['notebook']:
                        submission['notebook'] = f
                        nbviolations = []
                        for validator in self.validators:
                            violations = validator.validate(submission, f)
                            if violations:
                                if validator.is_warn_only():
                                    for e in violations:
                                        logging.warn(e)
                                else:
                                    submission['invalid'] = True
                                    nbviolations.extend(violations)

                        if self.interactive and submission['invalid']:
                            print()
                            logging.warning("%d violation(s) found: " %
                                            len(nbviolations))
                            for e in nbviolations:
                                logging.warning(e)

                            no = {'no', 'n'}
                            choice = input("Is this dangerous?\n"
                                           "(this notebook will NOT "
                                           "be executed for autograding "
                                           "if you answer 'y') ")
                            if choice in no:
                                submission['invalid'] = False
                                nbviolations.clear()

                        errors.extend(nbviolations)

                        if submission['invalid']:
                            targetfile = os.path.join(self.dangerous_dir,
                                                      submission['number'] +
                                                      '-' +
                                                      self.notebook_filename)
                        else:
                            os.makedirs(submission['dir'], exist_ok=True)
                            targetfile = os.path.join(submission['dir'],
                                                      self.notebook_filename)
                        shutil.copyfile(f, targetfile)
                    else:
                        e = ("collect_files %s: %s" %
                             (submission['number'],
                              "Multiple notebooks found in submission!"))

                        if e not in errors:
                            errors.append(e)
                elif os.path.isdir(f) and \
                        os.path.basename(f).lower() in self.datadir:
                    if not submission['datadir']:
                        logging.debug("Data dir found: %s" %
                                      os.path.basename(f))
                        submission['datadir'] = f
                        data_target_dir = os.path.join(submission['dir'],
                                                       os.path.basename(f))
                        os.makedirs(submission['dir'], exist_ok=True)

                        # copy with overwriting
                        if os.path.exists(data_target_dir):
                            logging.warning("Overwriting target %s with %s" %
                                            (data_target_dir, f))
                            shutil.rmtree(data_target_dir)
                        shutil.copytree(f, data_target_dir)

                    else:
                        e = ("collect_files %s: %s" %
                             (submission['number'],
                              "Multiple data dirs found in submission!"))

                        if e not in errors:
                            errors.append(e)

            if not submission['notebook']:
                e = "No notebook found in submission!"
                errors.append("collect_files %s: %s" % (submission['number'],
                                                        e))

        return files, errors

    def filterAndPrune(self, root, items):
        index = 0
        length = len(items)
        while index < length:
            i = items[index]
            if i.startswith('__MACOSX') or i.startswith('.'):
                del items[index]
                path = os.path.join(root, i)
                if os.path.isdir(path):
                    shutil.rmtree(path)
                elif os.path.isfile(path):
                    os.remove(path)
                else:
                    logging.warning('Error while pruning: unexpected path %s'
                                    % path)
                length -= 1
            else:
                index += 1

    def extract_zip(self, inputfile, target):
        patoolib.extract_archive(inputfile, outdir=target)
        extracted = []
        for root, dirs, files in os.walk(target, topdown=True):
            self.filterAndPrune(root, dirs)
            self.filterAndPrune(root, files)

            for f in files:
                extracted.append(os.path.join(root, f))
            for d in dirs:
                extracted.append(os.path.join(root, d))
        return extracted

    def generate_feedback(self, student, force):
        self.api.generate_feedback(self.assignment, student, force=force)
        self.api.release_feedback(self.assignment, student)

    def collect_feedback(self, student, output):
        self.generate_feedback(student, True)

        feedbackdir = 'feedback'
        html = os.path.join(feedbackdir, student, self.assignment,
                            os.path.splitext(self.notebook_filename)[0] +
                            '.html')

        if os.path.exists(html):
            target = os.path.join(output, student + '.html')
            logging.info("Collecting feedback from: %s" % html)
            shutil.copy(html, target)
            return 1

        return 0


def get_notebook_name(api, assignment):
    notebooks = api.get_notebooks(assignment)

    if not notebooks:
        return None

    return notebooks[0]['name'] + ".ipynb"


def setup():
    c = None
    my_glob = {'c': c, 'get_config': get_config}
    exec(compile(open('nbgrader_config.py', "rb").read(), 'nbgrader_config.py',
                 'exec'), my_glob)
    return NbGraderAPI(config=my_glob['c'])


def autograde(api, assignment, submissions, force):
    errors = []
    for submission in submissions:
        if submission['invalid']:
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


def main():
    coloredlogs.install(fmt='%(levelname)s %(message)s')
    coloredlogs.set_level(logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--assignment',
                        help='Name of the assignment',
                        type=str,
                        required=True)
    parser.add_argument('--dangerous',
                        help='Ignore validation warnings',
                        action="store_true")
    parser.add_argument('-i', '--interactive',
                        help='Pass --interactive to halt on validation errors',
                        action="store_true")
    parser.add_argument('-f', '--force',
                        help='Pass --force to nbgrader autograde',
                        action="store_true")
    parser.add_argument('-n', '--noop',
                        help='Do not run autograde and feedback',
                        action="store_true")
    parser.add_argument('-o', '--output',
                        help='Output directory for html feedback',
                        type=str,
                        default='upload')

    parser.add_argument('inputfiles', default=[], nargs='+')
    args = parser.parse_args()

    assignment = args.assignment
    output = os.path.join(args.output, assignment)

    api = setup()
    submissiondir = api.coursedir.submitted_directory
    notebook_filename = get_notebook_name(api, assignment)

    collectonly = args.noop

    if args.dangerous and args.interactive:
        logging.fatal("--dangerous and --interactive are mutually exclusive")
        raise RuntimeError

    if not notebook_filename:
        logging.fatal("No source notebooks found for assignment: %s" %
                      assignment)
        raise RuntimeError

    collector = Collector(api, assignment, notebook_filename)
    collector.set_data_dir(["data", "daten"])
    collector.set_dangerous_dir("dangerous")
    collector.set_interactive(args.interactive)

    collector.register_validator(IllegalStuffValidator(args.dangerous))

    submissions = []
    errors = []

    for inputfile in args.inputfiles:
        inputsubmissions, inputerrors = \
                collector.collect_submissions(inputfile, submissiondir)
        errors.extend(inputerrors)

        if inputsubmissions:
            submissions.extend(inputsubmissions)
            logging.info("Found %i submissions in %s." %
                         (len(inputsubmissions), inputfile))
        else:
            logging.fatal("No submissions found in %s." % inputfile)

    logging.info("Found a total of %i submissions." % len(submissions))
    if args.interactive:
        no = {'no', 'n'}
        choice = input("Continue with auto-grading? "
                       "(all valid notebooks will be executed) ")
        if choice in no:
            collectonly = True

    if collectonly:
        logging.info("autograding was disabled, exiting")
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
        logging.info("Collecting feedback for " + student)
        reports += collector.collect_feedback(student, output)

    logging.info("%d reports written to %s" % (reports, output))


if __name__ == "__main__":
    main()
