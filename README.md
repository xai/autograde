# Requirements

To handle zipped submissions, a respective unpacking tool must be present on the host system.  
- 7z: Most Linux distros provide a `p7zip` package.

## Using pip
`pip3 install --user coloredlogs patool`

## Using a virtual environment with pipenv
`pipenv install` installs the requirements defined in [Pipfile](./Pipfile),  
`pipenv shell` spawns a shell process to work in the virtual environment.

# Usage
```
usage: autograde.py [-h] -a ASSIGNMENT [--dangerous] [-i] [-f] [-n] [-o OUTPUT] inputfiles [inputfiles ...]

positional arguments:
  inputfiles

optional arguments:
  -h, --help            show this help message and exit
  -a ASSIGNMENT, --assignment ASSIGNMENT
                        Name of the assignment
  --dangerous           Ignore validation warnings
  -i, --interactive     Pass --interactive to halt on validation errors
  -f, --force           Pass --force to nbgrader autograde
  -n, --noop            Do not run autograde and feedback
  -o OUTPUT, --output OUTPUT
                        Output directory for html feedback
```

For example, when running  
`./autograde.py -a assignment-2 Submissions.zip`  

the following steps will be executed:
1. retrieve the correct notebook filename from `./source/assignment-2/`
2. collect student or group submissions from `Submissions.zip`: 
   - unpack (nested) zipped submissions
   - valid submissions go into `./submitted/(student|group)/assignment-2/`
   - submissions excluded by a validator go into `./dangerous/` instead
3. autograde each valid submission if it was not already autograded
4. list a summary of errors and problems encountered so far
4. wait and ask you to optionally perform additional formgrading using your browser
5. generate feedback for each submission and collect all `.html` files into `upload/assignment-2/`
