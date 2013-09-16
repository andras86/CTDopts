from CTDopts import CTDopts

# run this script with the following calls:

# python example.py --write_tool_ctd
# python example.py --write_tool_ctd test1.ctd
# python example.py --input_ctd test1.ctd -positive_number 8 -input_files file1.fastq file2.fastq
#                   -this_or_that that --write_param_ctd test2.ctd
# python example.py --input_ctd test2.ctd -boolean_flag
#
# now uncomment line 147 [tool_opts.finalize_log()] to log output along your parameters. Then uncomment 146 too!
# python example.py --input_ctd test2.ctd --write_param_ctd test2_log.ctd --log_output --log_std_streams
#
# if you want to log something other than stdout and stderr, comment line 146/147, uncomment 151 and run
# python example.py --input_ctd test2.ctd --write_param_ctd test2_log2.ctd --log_output

tool_opts = CTDopts(
    name='testTool',
    version='0.0.2',
    description='This is a dummy test tool presenting CTDopts usage',
    manual='manual',
    docurl='http://dummy.url/docurl.html',
    category='testing'
    )

main_params = tool_opts.get_root()

main_params.add(
    'positive_number',
    type=int,
    num_range=(0, None),
    default=5,
    description='A positive integer parameter'
    )

main_params.add(
    'boolean_flag',
    type=bool,  # is never required and it defaults to False
    description='A flag parameter. If --boolean_flag provided in command line: True, if not: False'
    )

main_params.add(
    'input_files',
    is_list=True,
    required=True,
    type=str,
    file_formats=['fastq', 'fastq.gz'],
    tags=['input file', 'required'],
    description='A list of filenames you want to feed this dummy program with'
    )

main_params.add(
    'this_or_that',
    type=str,
    choices=['this', 'that'],
    default='this',
    tags=['advanced'],
    description='A controlled vocabulary parameter. Allowed values: `this` or `that`'
    )

subparams = main_params.add_group('subparams', 'Further minor settings of some algorithm')

subparams.add(
    'param_1',
    type=float,
    tags=['advanced'],
    default=5.5,
    description='Some minor floating point setting'
    )

subparams.add(
    'param_2',
    is_list=True,
    type=float,
    tags=['advanced'],
    default=[0.0, 2.5, 5.0],
    description='A list of floating point settings for, say, multiple runs of analysis'
    )

minorparams = subparams.add_group('subsubsetting', 'A group of sub-subsettings')
minorparams.add(
    'param_3',
    type=int,
    tags=['advanced'],
    default=2,
    description="A subsetting's subsetting"
    )

# Tool parameter definition is over. Let's use them now.
#
# The tool could be called with the following command line arguments:
#
#   --write_tool_ctd <optional-filename>
#        Write testTool.ctd (or <optional-filename>) in the current directory and exit.
#        This is a tool-describing CTD, with default values for parameters that have them.
#
#   --input_ctd <filename>
#        Imports arguments from CTD file. Further command line arguments, if present, can be used
#        to override parameters in CTD.
#
#   --write_param_ctd <filename>
#        Outputs a CTD with the actual parameter values the tool was called with. If the tool was
#        called with an input CTD and some more command line arguments, it will do the overriding etc.
#
#   --log_output
#        If --write_param_ctd is set, this flag will enable the CTDopts object to have logging
#        capability. The user will have to call its finalize_log(stdout, stderr, exit_status) method
#         when everything that he/she intended to log is ready to be recorded. The stdout and stderr
#         arguments of the function can be strings or StringIO objects that the user is responsible
#         for building. Note: the user has to make sure finalize_log(...) gets called even if the
#         program crashes, otherwise nothing will be saved in a CTD. See --log_std_streams for
#         circumventing this.
#
#   --log_std_streams
#        This flag makes CTDopts hijack the stdout and stderr streams and log both seamlessly. If set,
#        the user doesn't have to deal with logging these streams, it will be done automatically, and
#        the CTD with logging information will be saved even if the program crashes.
#
#   normal command line parameters according to the definition above, with a single dash prefix.
#        -positive_number 8 -boolean_flag -input_files a1.fastq a2.fastq ...
#        Order of resolution: command line arguments > values in input CTD > default

args = tool_opts.parse_args()

print
print 'Arguments successfully loaded and verified against restrictions. We can start working with:\n', vars(args)

print
# accessing stuff just like argparse.
print 'Positive number parameter: ', args.positive_number
print 'This or that: ', args.this_or_that

# or dictionary interface like arg_dict['positive_number'] or arg_dict['subparams:param_1']
# subparameters can only be accessed like that anyway as colons can't be used in python identifiers.
# I don't really like this design choice and would go for nested namespaces personally.
arg_dict = vars(args)
print 'Subparameter 1: ', arg_dict['subparams:param_1']
print 'Input files:', ', '.join(arg_dict['input_files'])
print 'Boolean flag:', args.boolean_flag
print
print 'Doing stuff...'
print '...so we have some output to log. (if you called the tool with logging flags)'
print 'Finished.'

# # if you ran the script with --log_output --log_std_streams, include the following line
# 1/0  # and try it with uncommenting this too! The log will be complete and contain the error too.
tool_opts.finalize_log()

# # if you ran the script with --log_output and want control over what gets written into the
# # output and error nodes in the CTD, use this line (output, error, exit code):
# tool_opts.finalize_log('csoki', 'frici', 1)


# You can try running it with invalid parameters like -positive_number -10 or -input_files xxx.wrongextension etc.
# You'll get warnings. It used to give errors but it was voted against. Maybe we could make that a setting.
