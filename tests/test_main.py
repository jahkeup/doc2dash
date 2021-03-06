from __future__ import absolute_import, division, print_function

import errno
import logging
import os
import plistlib
import shutil
import sqlite3

import pytest

from mock import MagicMock, patch

import doc2dash

from doc2dash import __main__ as main


log = logging.getLogger(__name__)


@pytest.fixture
def args():
    """
    Return a mock of an argument object.
    """
    return MagicMock(name='args', A=False)


class TestArguments(object):
    def test_fails_without_source(self, capsys):
        """
        Fail If no source is passed.
        """
        with pytest.raises(SystemExit):
            main.main([])

        out, err = capsys.readouterr()
        assert out == ''
        assert (
            'error: too few arguments' in err
            or 'error: the following arguments are required: source' in err
        )

    def test_fails_with_unknown_icon(self, capsys):
        """
        Fail if icon is not PNG.
        """
        with pytest.raises(SystemExit):
            main.main(['foo', '-i', 'bar.bmp'])

        out, err = capsys.readouterr()
        assert err == ''
        assert 'Please supply a PNG icon.' in out

    def test_fails_with_inexistent_index_page(self, capsys):
        """
        Fail if an index is supplied but doesn't exit.
        """
        with pytest.raises(SystemExit):
            main.main(['foo', '-I', 'bar.html'])

        out, err = capsys.readouterr()
        assert err == ''
        assert 'Index file bar.html does not exists.' in out

    def test_handles_unknown_doc_types(self, monkeypatch, tmpdir):
        """
        If docs are passed but are unknown, exit with EINVAL.
        """
        monkeypatch.chdir(tmpdir)
        os.mkdir('foo')
        with pytest.raises(SystemExit) as e:
            main.main(['foo'])
        assert e.value.code == errno.EINVAL


def test_normal_flow(monkeypatch, tmpdir):
    """
    Integration test with a mocked out parser.
    """
    def _fake_prepare(args, dest):
        db_conn = sqlite3.connect(':memory:')
        db_conn.row_factory = sqlite3.Row
        db_conn.execute(
            'CREATE TABLE searchIndex(id INTEGER PRIMARY KEY, name TEXT, '
            'type TEXT, path TEXT)'
        )
        return 'data', db_conn

    def _yielder():
        yield 'testmethod', 'testpath', 'cm'

    monkeypatch.chdir(tmpdir)
    os.mkdir('foo')
    monkeypatch.setattr(main, 'prepare_docset', _fake_prepare)
    dt = MagicMock(detect=lambda _: True)
    dt.name = 'testtype'
    dt.return_value = MagicMock(parse=_yielder)
    monkeypatch.setattr(doc2dash.parsers, 'get_doctype', lambda _: dt)
    with patch('doc2dash.__main__.log.info') as info, \
            patch('os.system') as system, \
            patch('shutil.copy2') as cp:
        main.main(['foo', '-n', 'bar', '-a', '-i', 'qux.png'])
        # assert mock.call_args_list is None
        out = '\n'.join(call[0][0] for call in info.call_args_list) + '\n'
        assert system.call_args[0] == ('open -a dash "bar.docset"', )
        assert cp.call_args[0] == ('qux.png', 'bar.docset/icon.png')

    assert out == '''\
Converting testtype docs from "foo" to "bar.docset".
Parsing HTML...
Added 1 index entries.
Adding table of contents meta data...
Adding to dash...
'''


class TestSetupPaths(object):
    def test_works(self, args, monkeypatch, tmpdir):
        """
        Integration test with mocked-out parser.
        """
        foo_path = str(tmpdir.join('foo'))
        os.mkdir(foo_path)
        args.configure_mock(
            source=foo_path, name=None, destination=str(tmpdir)
        )
        assert (
            (foo_path, str(tmpdir.join('foo.docset')))
            == main.setup_paths(args)
        )
        abs_foo = os.path.abspath(foo_path)
        args.source = abs_foo
        assert ((abs_foo, str(tmpdir.join('foo.docset')) ==
                main.setup_paths(args)))
        assert args.name == 'foo'
        args.name = 'baz.docset'
        assert ((abs_foo, str(tmpdir.join('baz.docset')) ==
                main.setup_paths(args)))
        assert args.name == 'baz'

    def test_A_overrides_destination(self, args, monkeypatch):
        """
        Passing A computes the destination and overrides an argument.
        """
        assert '~' not in main.DEFAULT_DOCSET_PATH  # resolved?
        args.configure_mock(source='doc2dash', name=None, destination='foobar',
                            A=True)
        assert ('foo', os.path.join(main.DEFAULT_DOCSET_PATH, 'foo.docset') ==
                main.setup_paths(args))

    def test_detects_missing_source(self, args):
        """
        Exit wie ENOENT if source doesn't exist.
        """
        args.configure_mock(source='doesnotexist', name=None)
        with pytest.raises(SystemExit) as e:
            main.setup_paths(args)
        assert e.value.code == errno.ENOENT

    def test_detects_source_is_file(self, args):
        """
        Exit with ENOTDIR if a file is passed as source.
        """
        args.configure_mock(source='setup.py', name=None)
        with pytest.raises(SystemExit) as e:
            main.setup_paths(args)
        assert e.value.code == errno.ENOTDIR

    def test_detects_existing_dest(self, args, tmpdir, monkeypatch):
        """
        Exit with EEXIST if the selected destination already exists.
        """
        monkeypatch.chdir(tmpdir)
        os.mkdir('foo')
        os.mkdir('foo.docset')
        args.configure_mock(source='foo', force=False, name=None,
                            destination=None, A=False)
        with pytest.raises(SystemExit) as e:
            main.setup_paths(args)
        assert e.value.code == errno.EEXIST

        args.force = True
        main.setup_paths(args)
        assert not os.path.lexists('foo.docset')


class TestPrepareDocset(object):
    def test_plist_creation(self, args, monkeypatch, tmpdir):
        """
        All arguments should be reflected in the plist.
        """
        monkeypatch.chdir(tmpdir)
        m_ct = MagicMock()
        monkeypatch.setattr(shutil, 'copytree', m_ct)
        os.mkdir('bar')
        args.configure_mock(
            source='some/path/foo', name='foo', index_page=None)
        main.prepare_docset(args, 'bar')
        m_ct.assert_called_once_with(
            'some/path/foo',
            'bar/Contents/Resources/Documents',
        )
        assert os.path.isfile('bar/Contents/Resources/docSet.dsidx')
        p = plistlib.readPlist('bar/Contents/Info.plist')
        assert p == {
            'CFBundleIdentifier': 'foo',
            'CFBundleName': 'foo',
            'DocSetPlatformFamily': 'foo',
            'DashDocSetFamily': 'python',
            'isDashDocset': True,
        }
        with sqlite3.connect('bar/Contents/Resources/docSet.dsidx') as db_conn:
            cur = db_conn.cursor()
            # ensure table exists and is empty
            cur.execute('select count(1) from searchIndex')
            assert cur.fetchone()[0] == 0

    def test_with_index_page(self, args, monkeypatch, tmpdir):
        """
        If an index page is passed, it is added to the plist.
        """
        monkeypatch.chdir(tmpdir)
        m_ct = MagicMock()
        monkeypatch.setattr(shutil, 'copytree', m_ct)
        os.mkdir('bar')
        args.configure_mock(
            source='some/path/foo', name='foo', index_page='foo.html')
        main.prepare_docset(args, 'bar')
        p = plistlib.readPlist('bar/Contents/Info.plist')
        assert p == {
            'CFBundleIdentifier': 'foo',
            'CFBundleName': 'foo',
            'DocSetPlatformFamily': 'foo',
            'DashDocSetFamily': 'python',
            'isDashDocset': True,
            'dashIndexFilePath': 'foo.html',
        }


class TestSetupLogging(object):
    @pytest.mark.parametrize(
        "verbose, quiet, expected", [
            (False, False, logging.INFO),
            (True, False, logging.DEBUG),
            (False, True, logging.ERROR),
        ]
    )
    def test_logging(self, args, verbose, quiet, expected):
        """
        Ensure verbosity options cause the correct log level.
        """
        args.configure_mock(verbose=verbose, quiet=quiet)
        assert main.determine_log_level(args) is expected

    def test_quiet_and_verbose(self, args):
        """
        Fail if both -q and -v are passed.
        """
        args.configure_mock(verbose=True, quiet=True)
        with pytest.raises(ValueError):
            main.determine_log_level(args)

    def test_quiet_and_verbose_integration(self):
        """
        Ensure main() exists on -q + -v
        """
        with pytest.raises(SystemExit):
            main.main(['foo', '-q', '-v'])
