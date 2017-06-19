﻿from __future__ import print_function, unicode_literals, division

import os
import re
import codecs
import platform

from subprocess import check_output
from tempfile import mkdtemp
from functools import partial
import subprocess
try:
    from configparser import ConfigParser
except ImportError:
    from ConfigParser import ConfigParser

from pyrouge.utils import log
from pyrouge.utils.file_utils import DirectoryProcessor
from pyrouge.utils.file_utils import verify_dir


class MyRouge155(object):
    """
    This is a wrapper for the ROUGE 1.5.5 summary evaluation package.
    This class is designed to simplify the evaluation process by:

        1) Converting summaries into a format ROUGE understands.
        2) Generating the ROUGE configuration file automatically based
            on filename patterns.

    This class can be used within Python like this:

    rouge = MyRouge155()
    rouge.system_dir = 'test/systems'
    rouge.model_dir = 'test/models'

    # The system filename pattern should contain one group that
    # matches the document ID.
    rouge.system_filename_pattern = 'SL.P.10.R.11.SL062003-(\d+).html'

    # The model filename pattern has '#ID#' as a placeholder for the
    # document ID. If there are multiple model summaries, pyrouge
    # will use the provided regex to automatically match them with
    # the corresponding system summary. Here, [A-Z] matches
    # multiple model summaries for a given #ID#.
    rouge.model_filename_pattern = 'SL.P.10.R.[A-Z].SL062003-#ID#.html'

    rouge_output = rouge.evaluate()
    print(rouge_output)
    output_dict = rouge.output_to_dict(rouge_ouput)
    print(output_dict)
    ->    {'rouge_1_f_score': 0.95652,
         'rouge_1_f_score_cb': 0.95652,
         'rouge_1_f_score_ce': 0.95652,
         'rouge_1_precision': 0.95652,
        [...]


    To evaluate multiple systems:

        rouge = MyRouge155()
        rouge.system_dir = '/PATH/TO/systems'
        rouge.model_dir = 'PATH/TO/models'
        for system_id in ['id1', 'id2', 'id3']:
            rouge.system_filename_pattern = \
                'SL.P/.10.R.{}.SL062003-(\d+).html'.format(system_id)
            rouge.model_filename_pattern = \
                'SL.P.10.R.[A-Z].SL062003-#ID#.html'
            rouge_output = rouge.evaluate(system_id)
            print(rouge_output)

    """

    def __init__(self, rouge_dir=None, rouge_args=None):
        """
        Create a MyRouge155 object.

            rouge_dir:  Directory containing Rouge-1.5.5.pl
            rouge_args: Arguments to pass through to ROUGE if you
                        don't want to use the default pyrouge
                        arguments.

        """
        self.log = log.get_global_console_logger()
        self.__set_dir_properties()
        self._config_file = None
        self._settings_file = r"D:\Program Files\Python2.7.9\Lib\site-packages\pyrouge\settings.ini" #self.__get_config_path()
        self.__set_rouge_dir(rouge_dir)
        self.args = self.__clean_rouge_args(rouge_args)
        self._system_filename_pattern = None
        self._model_filename_pattern = None

    def save_home_dir(self):
        config = ConfigParser()
        section = 'pyrouge settings'
        config.add_section(section)
        config.set(section, 'home_dir', self._home_dir)
        with open(self._settings_file, 'w') as f:
            config.write(f)
        self.log.info("Set ROUGE home directory to {}.".format(self._home_dir))

    @property
    def settings_file(self):
        """
        Path of the setttings file, which stores the ROUGE home dir.

        """
        return self._settings_file

    @property
    def bin_path(self):
        """
        The full path of the ROUGE binary (although it's technically
        a script), i.e. rouge_home_dir/ROUGE-1.5.5.pl

        """
        if self._bin_path is None:
            raise Exception(
                "ROUGE path not set. Please set the ROUGE home directory "
                "and ensure that ROUGE-1.5.5.pl exists in it.")
        return self._bin_path

    @property
    def system_filename_pattern(self):
        """
        The regular expression pattern for matching system summary
        filenames. The regex string.

        E.g. "SL.P.10.R.11.SL062003-(\d+).html" will match the system
        filenames in the SPL2003/system folder of the ROUGE SPL example
        in the "sample-test" folder.

        Currently, there is no support for multiple systems.

        """
        return self._system_filename_pattern

    @system_filename_pattern.setter
    def system_filename_pattern(self, pattern):
        self._system_filename_pattern = pattern

    @property
    def model_filename_pattern(self):
        """
        The regular expression pattern for matching model summary
        filenames. The pattern needs to contain the string "#ID#",
        which is a placeholder for the document ID.

        E.g. "SL.P.10.R.[A-Z].SL062003-#ID#.html" will match the model
        filenames in the SPL2003/system folder of the ROUGE SPL
        example in the "sample-test" folder.

        "#ID#" is a placeholder for the document ID which has been
        matched by the "(\d+)" part of the system filename pattern.
        The different model summaries for a given document ID are
        matched by the "[A-Z]" part.

        """
        return self._model_filename_pattern

    @model_filename_pattern.setter
    def model_filename_pattern(self, pattern):
        self._model_filename_pattern = pattern

    @property
    def config_file(self):
        return self._config_file

    @config_file.setter
    def config_file(self, path):
        config_dir, _ = os.path.split(path)
        verify_dir(config_dir, "configuration file")
        self._config_file = path

    def split_sentences(self):
        """
        ROUGE requires texts split into sentences. In case the texts
        are not already split, this method can be used.

        """
        from pyrouge.utils.sentence_splitter import PunktSentenceSplitter
        self.log.info("Splitting sentences.")
        ss = PunktSentenceSplitter()
        sent_split_to_string = lambda s: "\n".join(ss.split(s))
        process_func = partial(
            DirectoryProcessor.process, function=sent_split_to_string)
        self.__process_summaries(process_func)

    @staticmethod
    def convert_summaries_to_rouge_format(input_dir, output_dir):
        """
        Convert all files in input_dir into a format ROUGE understands
        and saves the files to output_dir. The input files are assumed
        to be plain text with one sentence per line.

            input_dir:  Path of directory containing the input files.
            output_dir: Path of directory in which the converted files
                        will be saved.

        """
        DirectoryProcessor.process(
            input_dir, output_dir, MyRouge155.convert_text_to_rouge_format)

    @staticmethod
    def convert_text_to_rouge_format(text, title="dummy title"):
        """
        Convert a text to a format ROUGE understands. The text is
        assumed to contain one sentence per line.

            text:   The text to convert, containg one sentence per line.
            title:  Optional title for the text. The title will appear
                    in the converted file, but doesn't seem to have
                    any other relevance.

        Returns: The converted text as string.

        """
        sentences = text.split("\n")
        sent_elems = [
            "<a name=\"{i}\">[{i}]</a> <a href=\"#{i}\" id={i}>"
            "{text}</a>".format(i=i, text=sent)
            for i, sent in enumerate(sentences, start=1)]
        html = """<html>
<head>
<title>{title}</title>
</head>
<body bgcolor="white">
{elems}
</body>
</html>""".format(title=title, elems="\n".join(sent_elems))

        return html

    @staticmethod
    def write_config_static(system_dir, system_filename_pattern,
                            model_dir, model_filename_pattern,
                            config_file_path, system_id=None):
        """
        Write the ROUGE configuration file, which is basically a list
        of system summary files and their corresponding model summary
        files.

        pyrouge uses regular expressions to automatically find the
        matching model summary files for a given system summary file
        (cf. docstrings for system_filename_pattern and
        model_filename_pattern).

            system_dir:                 Path of directory containing
                                        system summaries.
            system_filename_pattern:    Regex string for matching
                                        system summary filenames.
            model_dir:                  Path of directory containing
                                        model summaries.
            model_filename_pattern:     Regex string for matching model
                                        summary filenames.
            config_file_path:           Path of the configuration file.
            system_id:                  Optional system ID string which
                                        will appear in the ROUGE output.

        """
        system_filenames = [f for f in os.listdir(system_dir)]
        system_models_tuples = []

        system_filename_pattern = re.compile(system_filename_pattern)
        for system_filename in sorted(system_filenames):
            match = system_filename_pattern.match(system_filename)
            if match:
                id = match.groups(0)[0]
                model_filenames = MyRouge155.__get_model_filenames_for_id(
                    id, model_dir, model_filename_pattern)
                system_models_tuples.append(
                    (system_filename, sorted(model_filenames)))
        if not system_models_tuples:
            raise Exception(
                "Did not find any files matching the pattern {} "
                "in the system summaries directory {}.".format(
                    system_filename_pattern.pattern, system_dir))

        with codecs.open(config_file_path, 'w', encoding='utf-8') as f:
            f.write('<ROUGE-EVAL version="1.55">')
            for task_id, (system_filename, model_filenames) in enumerate(
                    system_models_tuples, start=1):

                eval_string = MyRouge155.__get_eval_string(
                    task_id, system_id,
                    system_dir, system_filename,
                    model_dir, model_filenames)
                f.write(eval_string)
            f.write("</ROUGE-EVAL>")

    def write_config(self, config_file_path=None, system_id=None):
        """
        Write the ROUGE configuration file, which is basically a list
        of system summary files and their matching model summary files.

        This is a non-static version of write_config_file_static().

            config_file_path:   Path of the configuration file.
            system_id:          Optional system ID string which will
                                appear in the ROUGE output.

        """
        if config_file_path is not None:
            self._config_dir, config_filename = os.path.split(config_file_path)
        if not system_id:
            system_id = 1
        if (not config_file_path) or (not self._config_dir):
            self._config_dir = mkdtemp()
            config_filename = "rouge_conf.xml"
        else:
            config_dir, config_filename = os.path.split(config_file_path)
            verify_dir(config_dir, "configuration file")
        self._config_file = os.path.join(self._config_dir, config_filename)
        MyRouge155.write_config_staticA(
            self._system_dir, self._system_filename_pattern,
            self._model_dir, self._model_filename_pattern,
            self._config_file, system_id)
        self.log.info(
            "Written ROUGE configuration to {}".format(self._config_file))

    def evaluate(self, system_id='None',conf_path = None, PerlPath =ur'perl', rouge_args=None ):
        """
        Run ROUGE to evaluate the system summaries in system_dir against
        the model summaries in model_dir. The summaries are assumed to
        be in the one-sentence-per-line HTML format ROUGE understands.

            system_id:  Optional system ID which will be printed in
                        ROUGE's output.

        Returns: Rouge output as string.

        """
        print("input system id set:")
        print(system_id)
        self.write_config(system_id=system_id, config_file_path = conf_path)
        options = self.__get_options(rouge_args)
        command = [PerlPath] + [self._bin_path] + options
        print(command)
        self.log.info(
            "Running ROUGE with command {}".format(" ".join(command)))
        rouge_output = check_output(command).decode("UTF-8")
        return rouge_output

##    def evaluate(self, system_id=1,conf_path = None, rouge_args=None):
##        """
##        Run ROUGE to evaluate the system summaries in system_dir against
##        the model summaries in model_dir. The summaries are assumed to
##        be in the one-sentence-per-line HTML format ROUGE understands.
##
##            system_id:  Optional system ID which will be printed in
##                        ROUGE's output.
##
##        Returns: Rouge output as string.
##
##        """
##        self.write_config(system_id=system_id, config_file_path = conf_path)
##        options = self.__get_options(rouge_args)
##        command = [ur'D:\Perl\bin\perl'] + [self._bin_path] + options
##        print(command)
##        self.log.info(
##            "Running ROUGE with command {}".format(" ".join(command)))
##        process = subprocess.Popen(stdout=PIPE, command)
##        output, unused_err = process.communicate()
##        retcode = process.poll()
####        if retcode:
####           cmd = kwargs.get("args")
####           if cmd is None:
####              cmd = popenargs[0]
####           # raise CalledProcessError(retcode, cmd, output=output)
##        rouge_output = output.decode("UTF-8")
##        return rouge_output, retcode
    def convert_and_evaluate(self, system_id=1,
                             split_sentences=False, rouge_args=None):
        """
        Convert plain text summaries to ROUGE format and run ROUGE to
        evaluate the system summaries in system_dir against the model
        summaries in model_dir. Optionally split texts into sentences
        in case they aren't already.

        This is just a convenience method combining
        convert_summaries_to_rouge_format() and evaluate().

            split_sentences:    Optional argument specifying if
                                sentences should be split.
            system_id:          Optional system ID which will be printed
                                in ROUGE's output.

        Returns: ROUGE output as string.

        """
        if split_sentences:
            self.split_sentences()
        self.__write_summaries()
        rouge_output = self.evaluate(system_id, rouge_args)
        return rouge_output

    def output_to_dict(self, output):
        """
        Convert the ROUGE output into python dictionary for further
        processing.

        """
        #0 ROUGE-1 Average_R: 0.02632 (95%-conf.int. 0.02632 - 0.02632)
        pattern = re.compile(
            r"(\d+) (ROUGE-\S+) (Average_\w): (\d.\d+) "
            r"\(95%-conf.int. (\d.\d+) - (\d.\d+)\)")
        results = {}
        for line in output.split("\n"):
            match = pattern.match(line)
            if match:
                sys_id, rouge_type, measure, result, conf_begin, conf_end = \
                    match.groups()
                measure = {
                    'Average_R': 'recall',
                    'Average_P': 'precision',
                    'Average_F': 'f_score'
                    }[measure]
                rouge_type = rouge_type.lower().replace("-", '_')
                key = "{}_{}".format(rouge_type, measure)
                results[key] = float(result)
                results["{}_cb".format(key)] = float(conf_begin)
                results["{}_ce".format(key)] = float(conf_end)
        return results

    ###################################################################
    # Private methods

    def __set_rouge_dir(self, home_dir=None):
        """
        Verfify presence of ROUGE-1.5.5.pl and data folder, and set
        those paths.

        """
        if not home_dir:
            self._home_dir = self.__get_rouge_home_dir_from_settings()
        else:
            self._home_dir = home_dir
            self.save_home_dir()
        self._bin_path = os.path.join(self._home_dir, 'ROUGE-1.5.5.pl')
        self.data_dir = os.path.join(self._home_dir, 'data')
        if not os.path.exists(self._bin_path):
            raise Exception(
                "ROUGE binary not found at {}. Please set the "
                "correct path by running pyrouge_set_rouge_path "
                "/path/to/rouge/home.".format(self._bin_path))

    def __get_rouge_home_dir_from_settings(self):
        config = ConfigParser()
        with open(self._settings_file) as f:
            if hasattr(config, "read_file"):
                config.read_file(f)
            else:
                # use deprecated python 2.x method
                config.readfp(f)
        rouge_home_dir = config.get('pyrouge settings', 'home_dir')
        return rouge_home_dir

    @staticmethod
    def __get_eval_string(
            task_id, system_id,
            system_dir, system_filename,
            model_dir, model_filenames):
        """
        ROUGE can evaluate several system summaries for a given text
        against several model summaries, i.e. there is an m-to-n
        relation between system and model summaries. The system
        summaries are listed in the <PEERS> tag and the model summaries
        in the <MODELS> tag. pyrouge currently only supports one system
        summary per text, i.e. it assumes a 1-to-n relation between
        system and model summaries.

        """
        peer_elems = "<P ID=\"{id}\">{name}</P>".format(
            id=system_id, name=system_filename)
##        peer_elems = ''
##        if system_id[0] != 'None':
##            system_filename1 = system_filename.split('.')[:-1]
##            s1 = '.'.join(system_filename1)
##        else:
##            s1 = system_filename
##
##        for eachid in system_id:
##            peer_elems += "<P ID=\"{id}\">{name}.{id1}</P>\n".format(
##                id=eachid, id1=eachid,name=s1)

        model_elems = ["<M ID=\"{id}\">{name}</M>".format(
            id=chr(65 + i), name=name)
            for i, name in enumerate(model_filenames)]

        model_elems = "\n\t\t\t".join(model_elems)
        eval_string = """
    <EVAL ID="{task_id}">
        <MODEL-ROOT>{model_root}</MODEL-ROOT>
        <PEER-ROOT>{peer_root}</PEER-ROOT>
        <INPUT-FORMAT TYPE="SEE">
        </INPUT-FORMAT>
        <PEERS>
            {peer_elems}
        </PEERS>
        <MODELS>
            {model_elems}
        </MODELS>
    </EVAL>
""".format(
            task_id=task_id,
            model_root=model_dir, model_elems=model_elems,
            peer_root=system_dir, peer_elems=peer_elems)
        return eval_string

    def __process_summaries(self, process_func):
        """
        Helper method that applies process_func to the files in the
        system and model folders and saves the resulting files to new
        system and model folders.

        """
        temp_dir = mkdtemp()
        new_system_dir = os.path.join(temp_dir, "system")
        os.mkdir(new_system_dir)
        new_model_dir = os.path.join(temp_dir, "model")
        os.mkdir(new_model_dir)
        self.log.info(
            "Processing summaries. Saving system files to {} and "
            "model files to {}.".format(new_system_dir, new_model_dir))
        process_func(self._system_dir, new_system_dir)
        process_func(self._model_dir, new_model_dir)
        self._system_dir = new_system_dir
        self._model_dir = new_model_dir

    def __write_summaries(self):
        self.log.info("Writing summaries.")
        self.__process_summaries(self.convert_summaries_to_rouge_format)

    @staticmethod
    def __get_model_filenames_for_id(id, model_dir, model_filenames_pattern):
        pattern = re.compile(model_filenames_pattern.replace('#ID#', id))
        model_filenames = [
            f for f in os.listdir(model_dir) if pattern.match(f)]
        if not model_filenames:
            raise Exception(
                "Could not find any model summaries for the system"
                " summary with ID {}. Specified model filename pattern was: "
                "{}".format(id, model_filenames_pattern))
        return model_filenames

    def __get_options(self, rouge_args=None):
        """
        Get supplied command line arguments for ROUGE or use default
        ones.

        """
        if self.args:
            options = self.args.split()
        elif rouge_args:
            options = rouge_args.split()
        else:
            options = [
                '-e', self._data_dir,
                '-c', 95,
                '-U',
                '-r', 1000,
                '-n', 4,
                '-a',
                ]
##            options = [
##                '-e', self._data_dir,
##                '-c', 95,
##                '-2',
##                '-U',
##                '-r', 1000,
##                '-n', 4,
##                '-w', 1.2,
##                '-a',
##                ]
            options = list(map(str, options))

        options = self.__add_config_option(options)
        return options

    def __create_dir_property(self, dir_name, docstring):
        """
        Generate getter and setter for a directory property.

        """
        property_name = "{}_dir".format(dir_name)
        private_name = "_" + property_name
        setattr(self, private_name, None)

        def fget(self):
            return getattr(self, private_name)

        def fset(self, path):
            verify_dir(path, dir_name)
            setattr(self, private_name, path)

        p = property(fget=fget, fset=fset, doc=docstring)
        setattr(self.__class__, property_name, p)

    def __set_dir_properties(self):
        """
        Automatically generate the properties for directories.

        """
        directories = [
            ("home", "The ROUGE home directory."),
            ("data", "The path of the ROUGE 'data' directory."),
            ("system", "Path of the directory containing system summaries."),
            ("model", "Path of the directory containing model summaries."),
            ]
        for (dirname, docstring) in directories:
            self.__create_dir_property(dirname, docstring)

    def __clean_rouge_args(self, rouge_args):
        """
        Remove enclosing quotation marks, if any.

        """
        if not rouge_args:
            return
        quot_mark_pattern = re.compile('"(.+)"')
        match = quot_mark_pattern.match(rouge_args)
        if match:
            cleaned_args = match.group(1)
            return cleaned_args
        else:
            return rouge_args

    def __add_config_option(self, options):
        return options + ['-m'] + [self._config_file]

    def __get_config_path(self):
        if platform.system() == "Windows":
            parent_dir = os.getenv("APPDATA")
            config_dir_name = "pyrouge"
        elif os.name == "posix":
            parent_dir = os.path.expanduser("~")
            config_dir_name = ".pyrouge"
        else:
            parent_dir = os.path.dirname(__file__)
            config_dir_name = ""
        config_dir = os.path.join(parent_dir, config_dir_name)
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        return os.path.join(config_dir, 'settings.ini')

    @staticmethod
    def __get_eval_stringA(
            task_id, system_id,
            system_dir, system_filenames,
            model_dir, model_filenames):
        """
        ROUGE can evaluate several system summaries for a given text
        against several model summaries, i.e. there is an m-to-n
        relation between system and model summaries. The system
        summaries are listed in the <PEERS> tag and the model summaries
        in the <MODELS> tag. pyrouge currently only supports one system
        summary per text, i.e. it assumes a 1-to-n relation between
        system and model summaries.

        """

##        peer_elems = "<P ID=\"{id}\">{name}</P>".format(
##            id=system_id, name=system_filename)
        peer_elems_set = ""
        for eachpeer in system_filenames:
            system_id = eachpeer[1]
            system_filename = eachpeer[2]
            peer_elems = "<P ID=\"{id}\">{name}</P>\n\t\t\t".format(
                id=system_id, name=system_filename)
            peer_elems_set = peer_elems_set + peer_elems
##        peer_elems = ''
##        if system_id[0] != 'None':
##            system_filename1 = system_filename.split('.')[:-1]
##            s1 = '.'.join(system_filename1)
##        else:
##            s1 = system_filename
##
##        for eachid in system_id:
##            peer_elems += "<P ID=\"{id}\">{name}.{id1}</P>\n".format(
##                id=eachid, id1=eachid,name=s1)

        model_elems = ["<M ID=\"{id}\">{name}</M>".format(
            id=chr(65 + i), name=name)
            for i, name in enumerate(model_filenames)]

        model_elems = "\n\t\t\t".join(model_elems)
        eval_string = """
    <EVAL ID="{task_id}">
        <MODEL-ROOT>{model_root}</MODEL-ROOT>
        <PEER-ROOT>{peer_root}</PEER-ROOT>
        <INPUT-FORMAT TYPE="SEE">
        </INPUT-FORMAT>
        <PEERS>
            {peer_elems}
        </PEERS>
        <MODELS>
            {model_elems}
        </MODELS>
    </EVAL>
""".format(
            task_id=task_id,
            model_root=model_dir, model_elems=model_elems,
            peer_root=system_dir, peer_elems=peer_elems_set)
        return eval_string
    @staticmethod
    def ProduceSysModPair(system_dir,model_dir,system_idset,model_filenames_pattern,system_filename_pattern):
##        system_dir = r'D:\pythonwork\code\paperparse\paper\papers\system4_html'
##        model_dir = r'D:\pythonwork\code\paperparse\paper\papers\model3_html'
##        system_idset = ['01','02','03','04','05','06','07']
##        model_filenames_pattern = r'p14-#ID#.xhtml.[A-Z].html'
##        system_filename_pattern =r'P14-(\d+).xhtml.html.0[1-7]'
##        perlpathname=r'D:\Perl\bin\perl'
        system_filenames = os.listdir(system_dir)
        all_id_system_file =[]
        for eachdir in system_idset:
#            systempattern = r'P14-(\d+).xhtml.html.'+eachdir
            syspattern =system_filename_pattern + '.' +eachdir + '$'
            system_re = re.compile(syspattern)
            id_file_set = []
            for system_filename in sorted(system_filenames):
                match = system_re.match(system_filename)
                if match:
                    id = match.groups(0)[0]
                    system_id = eachdir
                    system_filename
                    id_file_set.append([id,system_id,system_filename])
         #           print [id,system_id,system_filename]
            all_id_system_file.append(id_file_set)
        model_files_for_each_system = []
        i = 0;
        model_system_tuple = []
        for eachsystem in all_id_system_file[0]:
            model_file_set = MyRouge155.__get_model_filenames_for_id(eachsystem[0],model_dir,model_filenames_pattern)
            system_id_set = []
            for eachsystemset in all_id_system_file:
                system_id_set.append(eachsystemset[i])
            i = i + 1
            model_files_for_each_system.append(model_file_set)
            model_system_tuple.append([system_id_set,model_file_set])
            #print system_id_set,model_file_set
        return model_system_tuple
    @staticmethod
    def write_config_staticA(system_dir, system_filename_pattern,
                            model_dir, model_filename_pattern,
                            config_file_path, system_id=None):
        """
        Write the ROUGE configuration file, which is basically a list
        of system summary files and their corresponding model summary
        files.

        pyrouge uses regular expressions to automatically find the
        matching model summary files for a given system summary file
        (cf. docstrings for system_filename_pattern and
        model_filename_pattern).

            system_dir:                 Path of directory containing
                                        system summaries.
            system_filename_pattern:    Regex string for matching
                                        system summary filenames.
            model_dir:                  Path of directory containing
                                        model summaries.
            model_filename_pattern:     Regex string for matching model
                                        summary filenames.
            config_file_path:           Path of the configuration file.
            system_id:                  Optional system ID string which
                                        will appear in the ROUGE output.

        """
        system_filenames = [f for f in os.listdir(system_dir)]
##        system_models_tuples = []
##
##        system_re = re.compile(system_filename_pattern)
##        for system_filename in sorted(system_filenames):
##            match = system_re.match(system_filename)
##            if match:
##                id = match.groups(0)[0]
##                model_filenames = MyRouge155.__get_model_filenames_for_id(
##                    id, model_dir, model_filename_pattern)
##                system_models_tuples.append(
##                    (system_filename, sorted(model_filenames)))
##        if not system_models_tuples:
##            raise Exception(
##                "Did not find any files matching the pattern {} "
##                "in the system summaries directory {}.".format(
##                    system_re.pattern, system_dir))

        print('begin parse system_model pair')
        print(system_dir)
        print(model_dir)
        print(system_id)
        print(model_filename_pattern)
        print(system_filename_pattern)
        sys_mod = MyRouge155.ProduceSysModPair(system_dir,model_dir,system_id,model_filename_pattern,system_filename_pattern)
        print('Parsesystemmodelpairok begin write xml file')
        with codecs.open(config_file_path, 'w', encoding='utf-8') as f:
            f.write('<ROUGE-EVAL version="1.55">')
            for task_id, (system_filenames, model_filenames) in enumerate(
                sys_mod, start=1):

               eval_string = MyRouge155.__get_eval_stringA(task_id, system_id,system_dir, system_filenames,model_dir, model_filenames)
               f.write(eval_string)
            f.write("</ROUGE-EVAL>")
def TestMyRouge():
    system_dir = r'D:\pythonwork\code\paperparse\paper\papers\system4_html'
    model_dir = r'D:\pythonwork\code\paperparse\paper\papers\model3_html'
    system_idset = ['01','02','03','04','05','06','07']
    model_filename_pattern = r'p14-#ID#.xhtml.[A-Z].html'
    system_filename_pattern =r'P14-(\d+).xhtml.html.0[1-7]'
    config_file_path  = r'D:\pythonwork\code\paperparse\paper\rouge_conf.xml'
    perlpathname=r'perl'
    sys_mod = MyRouge155.ProduceSysModPair(system_dir,model_dir,system_idset,model_filename_pattern,system_filename_pattern)
##    for eachtuple in sys_mod:
##        print eachtuple
##    system_id = "none"
##    for task_id, (system_filenames, model_filenames) in enumerate(
##        sys_mod, start=1):
##        print task_id
##        evalstr = MyRouge155.get_eval_stringA(task_id, system_id,system_dir, system_filenames,model_dir, model_filenames)
##        print evalstr
    MyRouge155.write_config_staticA(system_dir, system_filename_pattern,
                            model_dir, model_filename_pattern,
                            config_file_path, system_id=system_idset)
if __name__ == "__main__":
    TestMyRouge()
##    import argparse
##    from utils.argparsers import rouge_path_parser
##
##    parser = argparse.ArgumentParser(parents=[rouge_path_parser])
##    args = parser.parse_args()
##
##    rouge = MyRouge155(args.rouge_home)
##    rouge.save_home_dir()
