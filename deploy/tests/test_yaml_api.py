from abc import ABC, abstractmethod
from fabric.api import env
import logging
import os
from os import fspath
from pathlib import Path
from pprint import pprint
import pytest
import re
import shlex
try:
    # shlex.join is added in 3.8
    from shlex import join as shjoin
except ImportError:
    def shjoin(iterable):
        return ' '.join([shlex.quote(_) for _ in iterable])

import sure
from textwrap import dedent
from unittest.mock import patch
import yaml

import firesim


from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from _yaml import _ReadStream


rootLogger = logging.getLogger()

# In case you put any package-level tests, make sure they use the test credentials too
pytestmark = pytest.mark.usefixtures("aws_test_credentials")


class TmpYaml:
    """Encapsulate our pattern for using sample-backup-configs"""
    def __init__(self, tmp_dir: Path, sample_config: Path) -> None:
        """
        Args:
            tmp_dir: path to temporary directory
            sample_config: path to the sample config that is
                           used to initialize our data
        """
        config_name = sample_config.name

        (tmp_name, nsubs) = re.subn(r'^sample_', 'test_', config_name)
        nsubs.should.equal(1)

        self.path = tmp_dir / tmp_name
        with sample_config.open('r') as f:
            self.load(f)

    def load(self, stream:'_ReadStream') -> None:
        self.data = yaml.safe_load(stream)

    def dump(self) -> None:
        self.path.write_text(yaml.dump(self.data))

class TmpYamlSet(ABC):
    """Aggregate Fixture Encapsulating group of configs that get populated by the sample-backup-configs
       by default and can be manipulated either via YAML api or clobbering them
       with a string

       each 'TestConfig' has a:
         * path: pathlib.Path to a tempfile location where the config will be written
         * data: python datastructure that is set via yaml.safe_load

       Methods:

    """
    @abstractmethod
    def __init__(self) -> None:
        pass

    @abstractmethod
    def write(self) -> None:
        """Iterates the TmpYaml members calling their dump"""
        pass

    @property
    @abstractmethod
    def args(self) -> list:
        """Returns list of cmdline options needed for firesim argparser"""
        pass

    @property
    @abstractmethod
    def cmdline(self) -> str:
        """Returns string of cmdline options needed for firesim argparser"""
        pass

class BuildTmpYamlSet(TmpYamlSet):
    """Concrete TmpYamlSet for build configs

    Attributes:
    """
    build: TmpYaml
    recipes: TmpYaml
    farm: TmpYaml
    hwdb: TmpYaml

    def __init__(self, build, recipes, farm, hwdb):
        self.build = build
        self.recipes = recipes
        self.farm = farm
        self.hwdb = hwdb

    def write(self):
        self.build.dump()
        self.recipes.dump()
        self.farm.dump()
        self.hwdb.dump()

    @property
    def args(self):
        return ['-b', fspath(self.build.path),
                '-r', fspath(self.recipes.path),
                '-s', fspath(self.farm.path),
                '-a', fspath(self.hwdb.path),
                ]

    @property
    def cmdline(self):
        return shjoin(self.args)

class RunTmpYamlSet(TmpYamlSet):
    """Concrete TmpYamlSet for run configs

    Attributes:
    """
    hwdb: TmpYaml
    run: TmpYaml

    def __init__(self, hwdb, run):
        self.hwdb = hwdb
        self.run = run

    def write(self):
        self.hwdb.dump()
        self.run.dump()

    @property
    def args(self):
        return ['-a', fspath(self.hwdb.path),
                '-c', fspath(self.run.path)]

    @property
    def cmdline(self):
        return shjoin(self.args)

@pytest.fixture()
def sample_backup_configs() -> Path:
    dir = Path(__file__).parent.parent / 'sample-backup-configs'
    dir.is_dir().should.equal(True)
    return dir

@pytest.fixture()
def scy_build(tmp_path: Path, sample_backup_configs: Path) -> TmpYaml:
    return TmpYaml(tmp_path, sample_backup_configs / 'sample_config_build.yaml')

@pytest.fixture()
def scy_build_recipes(tmp_path: Path, sample_backup_configs: Path) -> TmpYaml:
    return TmpYaml(tmp_path, sample_backup_configs / 'sample_config_build_recipes.yaml')

@pytest.fixture()
def scy_build_farm(tmp_path: Path, sample_backup_configs: Path) -> TmpYaml:
    return TmpYaml(tmp_path, sample_backup_configs / 'sample_config_build_farm.yaml')

@pytest.fixture()
def build_yamls(scy_build, scy_build_recipes, scy_build_farm, scy_hwdb) -> BuildTmpYamlSet:
    return BuildTmpYamlSet(scy_build, scy_build_recipes, scy_build_farm, scy_hwdb)

@pytest.fixture()
def scy_hwdb(tmp_path: Path, sample_backup_configs: Path) -> TmpYaml:
    return TmpYaml(tmp_path, sample_backup_configs / 'sample_config_hwdb.yaml')

@pytest.fixture()
def scy_runtime(tmp_path: Path, sample_backup_configs: Path) -> TmpYaml:
    return TmpYaml(tmp_path, sample_backup_configs / 'sample_config_runtime.yaml')

@pytest.fixture()
def run_yamls(scy_hwdb: TmpYaml, scy_runtime: TmpYaml) -> RunTmpYamlSet:
    return RunTmpYamlSet(scy_hwdb, scy_runtime)

@pytest.fixture()
def non_existent_file(tmp_path):
    # tmp_path is builtin pytest fixture to get a per-test temporary directory that should be clean
    # but we still make sure that it doesn't exist before giving it
    file = tmp_path / 'GHOST_FILE'
    file.exists().should.equal(False)
    return file

@pytest.fixture()
def firesim_argparser():
    return firesim.construct_firesim_argparser()

@pytest.fixture()
def fs_cl2args(firesim_argparser):
    """fixture that bundles calling parse_args and shlex.split to abbreviate usage in tests"""
    return lambda x: firesim_argparser.parse_args(shlex.split(x))

@pytest.mark.usefixtures("aws_test_credentials")
class TestConfigBuildAPI:
    """ Test config_{build, build_recipes}.yaml APIs """

    # run_test("invalid-build-section")
    @patch('firesim.buildafi')
    def test_invalid_build_section(self, buildafi_mock, build_yamls, fs_cl2args):
        # @patch modifies the symbol table with our Mock but we're dispatching through
        # a dict and that needs to be patched as well, otherwise our mock won't be called but
        # the real function will be
        firesim.BUILD_TASKS['buildafi'] = buildafi_mock
        os.environ['FIRESIM_SOURCED'] = '1'
        # at the beginning of the test build_yamls contains the backup-sample-configs
        # but we can show exactly what we're doing different from the default by
        build_yamls.build.load(dedent("""
            builds:

            agfis-to-share:
                - testing-recipe-name

            share-with-accounts:
                INVALID_NAME: 123456789012
            """))

        build_yamls.write()
        args = fs_cl2args(' '.join(['buildafi']+build_yamls.args))
        pprint(build_yamls.build.data)
        firesim.main.when.called_with(args).should.throw(TypeError)
        buildafi_mock.assert_not_called()


    @patch('firesim.buildafi')
    def test_programmatic_invalid_build_section(self, buildafi_mock, build_yamls, firesim_argparser):
        # @patch modifies the symbol table with our Mock but we're dispatching through
        # a dict and that needs to be patched as well, otherwise our mock won't be called but
        # the real function will be
        firesim.BUILD_TASKS['buildafi'] = buildafi_mock
        os.environ['FIRESIM_SOURCED'] = '1'
        # at the beginning of the test build_yamls contains the backup-sample-configs
        # but we can show exactly what we're doing different from the default by
        # by programatically modifying from the sample to remove all the builds
        #build_yamls.build.data['builds'] = []
        # lol sometimes, it's hard to tell exactly how the yaml will get loaded because None is what you get
        build_yamls.build.data['builds'] = None
        build_yamls.write()
        args = firesim_argparser.parse_args(['buildafi'] + build_yamls.args)
        pprint(build_yamls.build.data)
        firesim.main.when.called_with(args).should.throw(TypeError)
        buildafi_mock.assert_not_called()


    # run_test("invalid-aws-ec2-inst-type")
    @pytest.mark.skip(reason="unclear as to what this is testing even in Abe's impl")
    @patch('firesim.buildafi')
    def test_invalid_aws_ec2_inst_type(self, buildafi_mock, build_yamls, firesim_argparser):

        # @patch modifies the symbol table with our Mock but we're dispatching through
        # a dict and that needs to be patched as well, otherwise our mock won't be called but
        # the real function will be
        firesim.BUILD_TASKS['buildafi'] = buildafi_mock

        os.environ['FIRESIM_SOURCED'] = '1'
        build_yamls.farm.data['ec2-build-farm']['args']['instance-type'] = 'INVALID_TYPE'
        build_yamls.write()
        args = firesim_argparser.parse_args(['buildafi'] + build_yamls.args)
        firesim.main(args)
        buildafi_mock.assert_not_called()


    # run_test("invalid-buildfarm-type")
    @pytest.mark.xfail(reason="uncomment default-build-farm, test recipe needs update")
    @patch('firesim.buildafi')
    def test_invalid_buildfarm_type(self, buildafi_mock, build_yamls, firesim_argparser):
        # @patch modifies the symbol table with our Mock but we're dispatching through
        # a dict and that needs to be patched as well, otherwise our mock won't be called but
        # the real function will be
        firesim.BUILD_TASKS['buildafi'] = buildafi_mock
        os.environ['FIRESIM_SOURCED'] = '1'

        build_yamls.build.load(dedent("""
            #default-build-farm: testing-build-farm
            builds:
                - testing-recipe-name

            agfis-to-share:
                - testing-recipe-name

            share-with-accounts:
                INVALID_NAME: 123456789012
            """))
        build_yamls.farm.load(dedent("""
            testing-build-farm:
                build-farm-type: INVALID_BUILD_FARM_TYPE
                args:
                    DUMMY-ARG: null
            """))
        build_yamls.recipes.load(dedent("""
            testing-recipe-name:
                DESIGN: TopModule
                TARGET_CONFIG: Config
                deploy-triplet: null
                PLATFORM_CONFIG: Config
                post-build-hook: null
                s3-bucket-name: TESTING_BUCKET_NAME
                build-farm: testing-build-farm
            """))
        build_yamls.write()
        args = firesim_argparser.parse_args(['buildafi'] + build_yamls.args)
        firesim.main.when.called_with(args).should.throw(KeyError, re.compile(r'INVALID_BUILD_FARM_TYPE'))
        buildafi_mock.assert_not_called()

    # run_test("invalid-aws-ec2-no-args")
    # run_test("invalid-unmanaged-no-args")
    @patch('firesim.buildafi')
    @pytest.mark.parametrize('farm_name',
                             ['ec2-build-farm',
                              pytest.param(
                                  'local-build-farm',
                                  marks=pytest.mark.xfail(reason="Doesn't fail before calling buildafi")
                              )])
    def test_invalid_farm_missing_args(self, buildafi_mock, build_yamls, firesim_argparser, farm_name):
        # @patch modifies the symbol table with our Mock but we're dispatching through
        # a dict and that needs to be patched as well, otherwise our mock won't be called but
        # the real function will be
        firesim.BUILD_TASKS['buildafi'] = buildafi_mock
        os.environ['FIRESIM_SOURCED'] = '1'

        build_yamls.farm.data[farm_name]['args'] = None

        build_yamls.write()
        args = firesim_argparser.parse_args(['buildafi'] + build_yamls.args)
        #firesim.main(args)
        firesim.main.when.called_with(args).should.throw(TypeError, re.compile(r'object is not subscriptable'))
        buildafi_mock.assert_not_called()


    # run_test("invalid-unmanaged-no-hosts")
    @pytest.mark.xfail(reason="No longer fails before buildafi is called")
    @patch('firesim.buildafi')
    def test_invalid_unmanaged_missing_args(self, buildafi_mock, build_yamls, firesim_argparser):
        # @patch modifies the symbol table with our Mock but we're dispatching through
        # a dict and that needs to be patched as well, otherwise our mock won't be called but
        # the real function will be
        firesim.BUILD_TASKS['buildafi'] = buildafi_mock
        os.environ['FIRESIM_SOURCED'] = '1'

        build_yamls.farm.data['local-build-farm']['args']['hosts'] = None

        build_yamls.write()
        args = firesim_argparser.parse_args(['buildafi'] + build_yamls.args)
        #firesim.main(args)
        firesim.main.when.called_with(args).should.throw(TypeError)
        buildafi_mock.assert_not_called()

    # test invalid config_build.yaml
    @patch('firesim.buildafi')
    @pytest.mark.parametrize('opt', ['-b',
                                     pytest.param('-r',
                                                  marks=pytest.mark.xfail(reason="Depends on managerinit being run beforehand.")
                                                  ),
                                     pytest.param('-s',
                                                  marks=pytest.mark.xfail(reason="Depends on managerinit being run beforehand.")
                                                  ),
                                    ])
    def test_config_existence(self, buildafi_mock, fs_cl2args, opt, non_existent_file):
        # @patch modifies the symbol table with our Mock but we're dispatching through
        # a dict and that needs to be patched as well, otherwise our mock won't be called but
        # the real function will be
        firesim.BUILD_TASKS['buildafi'] = buildafi_mock
        os.environ['FIRESIM_SOURCED'] = '1'
        args = fs_cl2args(f'buildafi {opt} "{non_existent_file}"')
        firesim.main.when.called_with(args).should.throw(FileNotFoundError, re.compile(r'GHOST_FILE'))
        buildafi_mock.assert_not_called()

@pytest.mark.usefixtures("aws_test_credentials")
class TestConfigRunAPI:
    """ Test config_{runtime, hwdb}.yaml APIs """

    # run_test("hwdb-invalid-afi")
    # run_test("runtime-invalid-hwconfig")
    # run_test("runtime-invalid-topology")
    # run_test("runtime-invalid-workloadname")

    @patch('firesim.runcheck')
    @pytest.mark.parametrize('opt',
                             ['-a',
                              pytest.param('-c',
                                          marks=pytest.mark.xfail(reason="Depends on managerinit being run beforehand.")
                                           )
                              ])
    def test_config_existence(self, checkconfig_mock, fs_cl2args, opt, non_existent_file):
        # @patch modifies the symbol table with our Mock but we're dispatching through
        # a dict and that needs to be patched as well, otherwise our mock won't be called but
        # the real function will be
        firesim.RUN_TASKS['checkconfig'] = checkconfig_mock
        os.environ['FIRESIM_SOURCED'] = '1'
        args = fs_cl2args(f'runcheck {opt} "{non_existent_file}"')
        firesim.main.when.called_with(args).should.throw(FileNotFoundError, re.compile(r'GHOST_FILE'))
        checkconfig_mock.assert_not_called()
