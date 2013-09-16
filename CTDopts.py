## todo: http://blog.vwelch.com/2011/04/combining-configparser-and-argparse.html

import sys
import warnings
import argparse
from collections import OrderedDict
from xml.etree.ElementTree import Element, SubElement, tostring, parse
from xml.dom.minidom import parseString
import datetime
import pytz
from StringIO import StringIO
import atexit

# # lxml's interface is almost the same as xml's but you can order element attribues with it
# # (not that you should do it but it's still nice to see parameter name as first attribute
# # for readability). But as lxml is not in the standard library I'll just leave its traces
# # around (search for LXML) if someone wants to use it.
# from lxml.etree import Element, SubElement, tostring, parse


class _NumericRange(object):
    def __init__(self, param_name, n_type, n_min=None, n_max=None):
        self.param_name = param_name
        self.n_type = n_type
        self.n_min = n_min
        self.n_max = n_max

    def argparse_type(self):
        def is_in_range(value):
            value = self.n_type(value)  # TODO: do we need a warning if 5.6 gets cast to 5?
            if self.n_min is not None and value < self.n_min:
                warnings.warn("Parameter %s value %s is below minimum %s" % (self.param_name, value, self.n_min))
            if self.n_max is not None and value > self.n_max:
                warnings.warn("Parameter %s value %s is above maximum %s" % (self.param_name, value, self.n_max))
            return value
        # we'll pass this function handle to argparse's `type` option that not only casts input as it
        # would normally but also performs a range check and stalls parsing if value is illegal
        return is_in_range

    def ctd_range_string(self):
        n_min = str(self.n_min) if self.n_min is not None else ''
        n_max = str(self.n_max) if self.n_max is not None else ''
        return '%s:%s' % (n_min, n_max)


class _FileFormat(object):
    def __init__(self, param_name, formats):
        self.param_name = param_name
        self.formats = formats

    def argparse_type(self):
        def legal_formats(filename):
            # os.path.splitext(filename)[1][1:] wouldn't handle *.fastq.gz or any double-extension
            for format in self.formats:
                if filename.endswith('.' + format):  # TODO: should we be lenient with letter case?
                    return filename
            else:
                warnings.warn("Parameter %s's file extension not in allowed list. Allowed: %s. Actual: %s" %
                    (self.param_name, '/'.join(self.formats), filename))
                return filename
        # similarly to NumericRange, this function object will perform argparse's type enforcing
        # w/ a filename extension checking step. One could even implement MIME-type checking here
        return legal_formats

    def ctd_format_string(self):
        return ','.join(('*.' + format for format in self.formats))


# This class can hijack sys.stdout with a transparent interface but forwarding all write and flush
# calls to any other stream object. Modeled after http://stackoverflow.com/a/16551730
# Usage: sys.stdout = _MultiStream(sys.stdout, own_StringIO_object)
class _MultiStream(object):
    def __init__(self, stream1, stream2):
        self._stream1 = stream1
        self._stream2 = stream2

    def __getattr__(self, attr, *args, **kwargs):
        return self._wrap(attr, *args, **kwargs)

    def _wrap(self, attr, *args, **kwargs):
        def g(*a, **kw):
            if hasattr(self._stream2, attr):  # if stream2 has the required method, run it
                getattr(self._stream2, attr, *args, **kwargs)(*a, **kw)
            return getattr(self._stream1, attr, *args, **kwargs)(*a, **kw)
        return g

    def __setattr__(self, name, value):
        if name in ('_stream1', '_stream2'):
            self.__dict__[name] = value
        else:
            return setattr(self._stream1, name, value)

    def __delattr__(self, name):
        return delattr(self._stream1, name)


class ArgumentItem(object):
    def __init__(self, name, parent, **kwargs):
        self.name = name
        self.parent = parent
        self.type = kwargs.get('type', str)
        self.tags = kwargs.get('tags', [])
        self.required = kwargs.get('required', False)
        self.description = kwargs.get('description', '')
        self.is_list = kwargs.get('is_list', False)

        default = kwargs.get('default', None)
        # enforce that default is the correct type if exists. Elementwise for lists
        self.default = None if default is None else map(self.type, default) if self.is_list else self.type(default)
        # same for choices. I'm starting to think it's really unpythonic and we should trust input. TODO
        choices = kwargs.get('choices', None)
        self.choices = None if choices is None else map(self.type, choices)

        if self.type == bool:
            assert self.is_list == False, "Boolean flag can't be a list type"
            self.required = False
            self.default = False  # enforce flags to default to False

        # Default value should exist IFF argument is not required.
        # TODO: if we can have optional list arguments they don't have to have a default? (empty list)
        if self.required:
            assert self.default is None, ('Required field `%s` has default value' % self.name)
        else:
            assert self.default is not None, ('Optional field `%s` has no default value' % self.name)

        self.restrictions = None
        if 'num_range' in kwargs:
            self.restrictions = _NumericRange(self.name, self.type, *kwargs['num_range'])
        elif 'file_formats' in kwargs:
            self.restrictions = _FileFormat(self.name, kwargs['file_formats'])

    def argparse_call(self):
        # return a dictionary to be keyword-fed to argparse's add_argument(name, **kws).
        kws = {}
        if self.is_list:
            kws['nargs'] = '+'  # TODO: maybe allow '?' if not required [see required vs default above]

        kws['help'] = self.description
        kws['required'] = self.required

        # we'll handle restrictions (numeric ranges & file formats) in argparse's type casting
        # step. So we don't run the values through int() but a function that checks values and
        # only casts to int if it range criteria are met. argparse_type() returns this function.
        kws['type'] = self.type if self.restrictions is None else self.restrictions.argparse_type()

        if self.choices is not None:
            kws['choices'] = self.choices
        if self.default is not None:
            kws['default'] = self.default

        # if we take explicit metavar definition away we run into http://bugs.python.org/issue11874
        # I don't exactly know why but it's an argparse bug for sure. Really strange.
        # Actually it's a good idea to not have those long group1:group2:... parts there anyway.
        # TODO: maybe allow setting it manually. Like having a self.etc dictionary where users
        # can pass further keyword arguments to argparse for full customization.
        kws['metavar'] = self.name.upper()

        # boolean flags are different: you mustn't set type and metavar, they are assigned implicitly
        if self.type == bool:
            kws['action'] = 'store_true'
            del kws['type']
            del kws['metavar']

        return kws

    def xml_node(self):
        value = self.call_value if hasattr(self, 'call_value') else self.default

        # name, value, type, description, tags, restrictions, supported_formats
        attribs = OrderedDict()
        attribs['name'] = self.name
        if not self.is_list:
            attribs['value'] = '' if value is None else str(value)
            if self.type == bool:
                attribs['value'] = 'true' if value else 'false'  # XS likes it lowercase
        attribs['type'] = {int: 'int', float: 'float', str: 'string', bool: 'boolean'}[self.type]
        attribs['description'] = self.description
        attribs['tags'] = ','.join(self.tags)

        if self.choices is not None:
            attribs['restrictions'] = ','.join(self.choices)
        elif isinstance(self.restrictions, _NumericRange):
            attribs['restrictions'] = self.restrictions.ctd_range_string()
        elif isinstance(self.restrictions, _FileFormat):
            attribs['supported_formats'] = self.restrictions.ctd_format_string()

        if self.is_list:
            top = Element('ITEMLIST', attribs)
            if value is not None:
                for d in value:
                    SubElement(top, 'LISTITEM', {'value': str(d)})
            return top
        else:
            return Element('ITEM', attribs)

    def param_commandline_name(self):
        # for nested parameters, if the parameter is in paramgroup1 > subparamgroup1 > param1
        # then the command line param name should be -paramgroup1:subparamgroup1:param1
        parent_groups = self.parent.get_group_lineage()
        return (':'.join(parent_groups + [self.name]))

    def append_argument(self, argparse_instance):
        argparse_instance.add_argument('-' + self.param_commandline_name(), **self.argparse_call())

    def store_call_value(self, call_dict):
        cl_name = self.param_commandline_name()
        if cl_name in call_dict:
            self.call_value = call_dict[cl_name]


class ArgumentGroup(object):
    def __init__(self, name, parent, description=""):
        self.name = name
        self.parent = parent
        self.description = description
        self.arguments = OrderedDict()

    def add(self, name, **kwargs):
        if name in self.arguments:
            warnings.warn('Name `%s` in subsection `%s` defined twice! Overriding first')

        self.arguments[name] = ArgumentItem(name, self, **kwargs)

    def add_group(self, name, description=""):
        if name in self.arguments:
            warnings.warn('Name `%s` in subsection `%s` defined twice! Overriding first')

        self.arguments[name] = ArgumentGroup(name, self, description)
        return self.arguments[name]

    def xml_node(self):
        top = Element('NODE', {'name': self.name, 'description': self.description})
        # TODO: if an ArgumentItem comes after an ArgumentGroup, the CTD won't validate.
        # Of course this should never happen if the argument tree is built properly but it would be
        # nice to take care of it if a user happens to randomly define his arguments and groups.
        # So first we could sort self.arguments (Items first, Groups after them).
        for arg in self.arguments.itervalues():
            top.append(arg.xml_node())
        return top

    def append_argument(self, argparse_instance):
        # argparse is buggy and won't display help messages for arguments that are doubly nested in
        # groups (although it parses them perfectly). So while it's possible and totally legal, one
        # should never call add_argument_group() on groups because it will ruin his help message
        # display. So we'll have to append all groups to the main parser needing this ugly hack
        # of keeping argparse_root and argparse_current objects side by side so nested groups can
        # always access the main parser and arguments can access their parent group.

        # arguments in subsections are named -subsection1:subsection2:argument in command line
        # so we need colon separated argument naming in non-top-level arguments.
        argparse_current = argparse_instance.add_argument_group(self.name, self.description)
        for name, arg in self.arguments.iteritems():
            arg.append_argument(argparse_current)

    def store_call_value(self, call_dict):
        for name, arg in self.arguments.iteritems():
            arg.store_call_value(call_dict)

    def get_group_lineage(self):
        if self.parent is None:
            return []
        else:
            return self.parent.get_group_lineage() + [self.name]


class CTDopts(object):
    def __init__(self, name, version, **kwargs):
        self.name = name
        self.version = version
        self.optional_attribs = kwargs  # description, manual, docurl, category (+executable stuff).
        self.main_node = ArgumentGroup('1', None, 'Instance "1" section for %s' % self.name)  # OpenMS legacy?

    def get_root(self):
        return self.main_node

    def generate_ctd_tree(self, with_logging=False):
        tool_attribs = OrderedDict()
        tool_attribs['version'] = self.version
        tool_attribs['name'] = self.name
        tool_attribs['xmlns:xsi'] = "http://www.w3.org/2001/XMLSchema-instance"
        tool_attribs['xsi:schemaLocation'] = "https://github.com/genericworkflownodes/CTDopts/raw/master/schemas/CTD_0_3.xsd"

        opt_attribs = ['docurl', 'category']
        for oo in opt_attribs:
            if oo in self.optional_attribs:
                tool_attribs[oo] = self.optional_attribs[oo]

        tool = Element('tool', tool_attribs)  # CTD root

        opt_elements = ['manual', 'description', 'executableName', 'executablePath']

        for oo in opt_elements:
            if oo in self.optional_attribs:
                SubElement(tool, oo).text = self.optional_attribs[oo]

        if with_logging:
            top_logs = SubElement(tool, 'logs')
            self.log_node = SubElement(top_logs, 'log') # TODO: this will be directly a son of tool! XXXXXXXXXXXXXXXXXXXXXX
            self.log_node.attrib['executionTimeStart'] = datetime.datetime.now(pytz.utc).isoformat()

        # # LXML SYNTAX
        # # again so ugly, but lxml is strict w/ namespace attrib. generation, you can't just add them
        # xsi = 'http://www.w3.org/2001/XMLSchema-instance'
        # params = SubElement(tool, 'PARAMETERS', {
        #     'version': '1.4',
        #     '{%s}noNamespaceSchemaLocation' % xsi: "http://open-ms.sourceforge.net/schemas/Param_1_4.xsd"},
        #     nsmap={'xsi': xsi})

        # XML.ETREE SYNTAX
        params = SubElement(tool, 'PARAMETERS', {
            'version': '1.6.2',
            'xmlns:xsi': "http://www.w3.org/2001/XMLSchema-instance",
            'xsi:noNamespaceSchemaLocation': "https://github.com/genericworkflownodes/CTDopts/raw/master/schemas/Param_1_6_2.xsd"
            })


        # This seems to be some OpenMS hack (defining name, description, version for the second
        # time) but I'll stick to it for consistency
        top_node = SubElement(params, 'NODE',
            name=self.name,
            description=self.optional_attribs.get('description', '')  # desc. is optional, may not have been set
            )

        SubElement(top_node, 'ITEM',
            name='version',
            value=self.version,
            type='string',
            description='Version of the tool that generated this parameters file.',
            tags='advanced'
            )

        # all the above was boilerplate, now comes the actual parameter tree generation
        args_top_node = self.main_node.xml_node()
        top_node.append(args_top_node)

        # # LXML w/ pretty print syntax
        # return tostring(tool, pretty_print=True, xml_declaration=True, encoding="UTF-8")

        # xml.etree syntax (no pretty print available, so we use xml.dom.minidom stuff)
        self.tool_xml_node = tool

    def finalize_log(self, stdout=None, stderr=None, exit_status=None):

        if hasattr(self, 'already_finalized'):  # see last lines of method why it's needed
            return

        self.log_node.attrib['executionTimeStop'] = datetime.datetime.now(pytz.utc).isoformat()
        if exit_status is not None:
            self.log_node.attrib['executionStatus'] = str(exit_status)

        if stdout is None:
            stdout = self.stdout_stream if hasattr(self, 'stdout_stream') else ''
        if stderr is None:
            stderr = self.stderr_stream if hasattr(self, 'stderr_stream') else ''

        if isinstance(stdout, StringIO):
            stdout.flush()
            stdout_data = stdout.getvalue()
        else:
            stdout_data = stdout

        if isinstance(stderr, StringIO):
            stderr.flush()
            stderr_data = stderr.getvalue()
        else:
            stderr_data = stderr

        SubElement(self.log_node, 'executionErrors').text = stderr_data
        SubElement(self.log_node, 'executionMessage').text = stdout_data

        self.write_ctd()
        print "Parameter and log container %s written to current directory successfully." % self.out_ctd_file
        # finalize_log() is registered with atexit if -log_std_streams is set, so it will be run at
        # the end no matter whether the manual trigger was already successful before.
        # As atexit.unregister() was introduced only in Python 3 we need to make sure it's not re-run
        # manually.
        self.already_finalized = True

    def write_ctd(self):
        if not hasattr(self, 'tool_xml_node'):
            self.generate_ctd_tree()
        with open(self.out_ctd_file, 'w') as f:
            xml_content = parseString(tostring(self.tool_xml_node, encoding="UTF-8")).toprettyxml()
            f.write(xml_content)

    def _register_parameter(self, element, base_name, is_root=False):
        colon = '' if is_root else ':'
        full_name = '%s%s%s' % (base_name, colon, element.attrib['name'])
        if element.tag == 'ITEM':
            if element.attrib['type'] == 'boolean':  # for booleans, only register them if they are 'true'
                if element.attrib['value'] == 'true':
                    self.ini_params[full_name] = [True]
            else:  # for non-booleans just take whatever we find in the 'value' attrib
                self.ini_params[full_name] = [element.attrib['value']]
        elif element.tag == 'ITEMLIST':
            self.ini_params[full_name] = [listitem.attrib['value'] for listitem in element]
        elif element.tag == 'NODE':
            for child in element:
                self._register_parameter(child, full_name, is_root=False)

    def read_ini(self, ini_file):
        ini = parse(ini_file)
        root = ini.getroot()

        # for INI compatibility (which is an xml with the <PARAMETERS> node torn out of a CTD)
        # we check whether <PARAMETERS> is the root of the xml or a child of <tool>
        param_root = root if root.tag == 'PARAMETERS' else root.find('PARAMETERS')
        parameters = param_root.find('NODE').find('NODE')

        self.ini_params = OrderedDict()

        for child in parameters:
            self._register_parameter(child, '-', is_root=True)

        # as range/file format/vocabulary checkers are already embedded in the argparse parser object
        # we can just generate the equivalent command line call quick&dirty and let argparse handle it.
        command_line = []
        for arg_name, values in self.ini_params.iteritems():
            # Required list parameters that are not set in a CTD but ARE set in command line
            # would result in parsing errors because the first encounter would be an empty list.
            # So we don't register them, in case they are registered later when parsing command line params.
            if len(values):
                command_line.append(arg_name)
                # for boolean flags, we don't add values after the param flag.
                # We recognize boolean flags by checking the registered value, which should be [True]
                # for them, and only for them.
                if values != [True]:
                    command_line.extend(values)

        # print 'INI file's equivalent command line call:\n', ' '.join(command_line)  # debug
        return command_line

    def parse_args(self, *args):

        # although argparse supports mutually exclusive arguments, it doesn't support argument groups
        # in mutexes. What we want is a mutually exclusive -write_tool_ctd vs -input_ctd vs full-fledged
        # commandline and since the latter part is an argument group, we have to find a way around
        # it ourselves. So we have a pre-parsing step where we check whether -write_tool_ctd or -input_ctd
        # was called, handle them if so, and if none of them were called we continue with regular
        # command line behaviour.

        preparser = argparse.ArgumentParser()
        preparser.add_argument('--write_tool_ctd', nargs='*')
        preparser.add_argument('--input_ctd', type=str)  # aka as INI files from earlier
        preparser.add_argument('--write_param_ctd', type=str)
        preparser.add_argument('--log_output', action='store_true')
        preparser.add_argument('--log_std_streams', action='store_true')
        directives, rest = preparser.parse_known_args(*args)

        # if -write_tool_ctd is provided, write tool-describing CTD and exit
        if directives.write_tool_ctd is not None:
            # check whether a filename was provided or not. If not, use filename generated from tool name
            self.out_ctd_file = self.name + '.ctd' if not directives.write_tool_ctd else directives.write_tool_ctd[0]
            self.write_ctd()
            print "Tool-describing %s written to current directory successfully. Exiting." % self.out_ctd_file
            sys.exit()
        else:
            # if -input_ctd was called, we create the argument list from the ini file and then we append
            # whatever else command line arguments we had (they will overwrite those in the ini)
            final_args = self.read_ini(directives.input_ctd) if directives.input_ctd is not None else []
            final_args.extend(rest)

            regular_parser = argparse.ArgumentParser()
            # we populate an argparse parser with the attributes defined in the CTDopts object...
            self.main_node.append_argument(regular_parser)

            # ...and parse our INI/commandline arguments
            parsed_args = regular_parser.parse_args(final_args)

            # we store all parameter values we were given in case the user wants to output it in an out-CTD
            # so starting from main_node, we traverse the tree and store actual values in elements

            self.main_node.store_call_value(vars(parsed_args))

            if directives.write_param_ctd:
                self.out_ctd_file = directives.write_param_ctd
                if directives.log_output:
                    self.generate_ctd_tree(with_logging=True)
                    if directives.log_std_streams:
                        self.stdout_stream = StringIO()
                        self.stderr_stream = StringIO()
                        sys.stdout = _MultiStream(sys.stdout, self.stdout_stream)
                        sys.stderr = _MultiStream(sys.stderr, self.stderr_stream)
                        atexit.register(self.finalize_log)
                    else:
                        # if -log_std_streams is unset, it's down to the user to log whatever he/she
                        # wants and pass it to finalize_log(stdout, stderr, exit_status) later
                        pass
                else:
                    self.generate_ctd_tree(with_logging=False)
                    self.write_ctd()
                    print "Parameter container %s written to current directory successfully." % self.out_ctd_file

                # self.finalize_log('xxxxx', 'yyyyy', 1)
                # self.write_ctd()



            return parsed_args
