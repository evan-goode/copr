import os
from copy import deepcopy
from unittest import mock
from flask import Flask

from coprs import app
from coprs.helpers import parse_package_name, generate_repo_url, \
    fix_protocol_for_frontend, fix_protocol_for_backend, pre_process_repo_url, \
    parse_repo_params, pagure_html_diff_changed, SubdirMatch, raw_commit_changes

from tests.coprs_test_case import CoprsTestCase


class TestHelpers(CoprsTestCase):

    def test_guess_package_name(self):
        EXP = {
            'wat-1.2.rpm': 'wat',
            'will-crash-0.5-2.fc20.src.rpm': 'will-crash',
            'will-crash-0.5-2.fc20.src': 'will-crash',
            'will-crash-0.5-2.fc20': 'will-crash',
            'will-crash-0.5-2': 'will-crash',
            'will-crash-0.5-2.rpm': 'will-crash',
            'will-crash-0.5-2.src.rpm': 'will-crash',
            'will-crash': 'will-crash',
            'pkgname7.src.rpm': 'pkgname7',
            'copr-frontend-1.14-1.git.65.9ba5393.fc20.noarch': 'copr-frontend',
            'noversion.fc20.src.rpm': 'noversion',
            'nothing': 'nothing',
            'ruby193': 'ruby193',
            'xorg-x11-fonts-ISO8859-1-75dpi-7.1-2.1.el5.noarch.rpm': 'xorg-x11-fonts-ISO8859-1-75dpi',
        }

        for pkg, expected in EXP.items():
            assert parse_package_name(pkg) == expected

    def test_generate_repo_url(self):
        test_sets = []

        http_url = "http://example.com/path"
        https_url = "https://example.com/path"

        mock_chroot = mock.MagicMock()
        mock_chroot.os_release = "fedora"
        mock_chroot.os_version = "20"

        test_sets.extend([
            dict(args=(mock_chroot, http_url),
                 expected="http://example.com/path/fedora-$releasever-$basearch/"),
            dict(args=(mock_chroot, https_url),
                 expected="https://example.com/path/fedora-$releasever-$basearch/")])

        m2 = deepcopy(mock_chroot)
        m2.os_version = "rawhide"

        test_sets.extend([
            dict(args=(m2, http_url),
                 expected="http://example.com/path/fedora-rawhide-$basearch/"),
            dict(args=(m2, https_url),
                 expected="https://example.com/path/fedora-rawhide-$basearch/")])

        m3 = deepcopy(mock_chroot)
        m3.os_release = "rhel7"
        m3.os_version = "7.1"

        test_sets.extend([
            dict(args=(m3, http_url),
                 expected="http://example.com/path/rhel7-7.1-$basearch/"),
            dict(args=(m3, https_url),
                 expected="https://example.com/path/rhel7-7.1-$basearch/")])

        app.config["USE_HTTPS_FOR_RESULTS"] = True
        for test_set in test_sets:
            result = generate_repo_url(*test_set["args"])
            assert result == test_set["expected"]

    def test_fix_protocol_for_backend(self):
        http_url = "http://example.com/repo"
        https_url = "https://example.com/repo"

        orig = app.config["ENFORCE_PROTOCOL_FOR_BACKEND_URL"]
        try:
            app.config["ENFORCE_PROTOCOL_FOR_BACKEND_URL"] = "https"
            assert fix_protocol_for_backend(https_url) == https_url
            assert fix_protocol_for_backend(http_url) == https_url

            app.config["ENFORCE_PROTOCOL_FOR_BACKEND_URL"] = "http"
            assert fix_protocol_for_backend(https_url) == http_url
            assert fix_protocol_for_backend(http_url) == http_url

            app.config["ENFORCE_PROTOCOL_FOR_BACKEND_URL"] = None
            assert fix_protocol_for_backend(https_url) == https_url
            assert fix_protocol_for_backend(http_url) == http_url

        except Exception as e:
            app.config["ENFORCE_PROTOCOL_FOR_BACKEND_URL"] = orig
            raise e
        app.config["ENFORCE_PROTOCOL_FOR_BACKEND_URL"] = orig

    def test_fix_protocol_for_frontend(self):
        http_url = "http://example.com/repo"
        https_url = "https://example.com/repo"

        orig = app.config["ENFORCE_PROTOCOL_FOR_FRONTEND_URL"]
        try:
            app.config["ENFORCE_PROTOCOL_FOR_FRONTEND_URL"] = "https"
            assert fix_protocol_for_frontend(https_url) == https_url
            assert fix_protocol_for_frontend(http_url) == https_url

            app.config["ENFORCE_PROTOCOL_FOR_FRONTEND_URL"] = "http"
            assert fix_protocol_for_frontend(https_url) == http_url
            assert fix_protocol_for_frontend(http_url) == http_url

            app.config["ENFORCE_PROTOCOL_FOR_FRONTEND_URL"] = None
            assert fix_protocol_for_frontend(https_url) == https_url
            assert fix_protocol_for_frontend(http_url) == http_url

        except Exception as e:
            app.config["ENFORCE_PROTOCOL_FOR_FRONTEND_URL"] = orig
            raise e
        app.config["ENFORCE_PROTOCOL_FOR_BACKEND_URL"] = orig

    def test_pre_process_repo_url(self):
        app = Flask(__name__)
        app.config["BACKEND_BASE_URL"] = "http://backend"

        test_cases = [
            ("http://example1.com/foo/$chroot/", "http://example1.com/foo/fedora-rawhide-x86_64/"),
            ("copr://someuser/someproject", "http://backend/results/someuser/someproject/fedora-rawhide-x86_64/"),
            ("copr://someuser/someproject?foo=bar&baz=10",
             "http://backend/results/someuser/someproject/fedora-rawhide-x86_64/"),
            ("http://example1.com/foo/$chroot?priority=10",
             "http://example1.com/foo/fedora-rawhide-x86_64"),
            ("http://example1.com/foo/$chroot?priority=10&foo=bar",
             "http://example1.com/foo/fedora-rawhide-x86_64?foo=bar"),
        ]
        with app.app_context():
            for url, exp in test_cases:
                assert pre_process_repo_url("fedora-rawhide-x86_64", url) == exp

    def test_parse_repo_params(self):
        test_cases = [
            ("copr://foo/bar", {}),
            ("copr://foo/bar?priority=10", {"priority": 10}),
            ("copr://foo/bar?priority=10&unexp1=baz&unexp2=qux", {"priority": 10}),
            ("http://example1.com/foo?priority=10", {"priority": 10}),
        ]
        for repo, exp in test_cases:
            assert parse_repo_params(repo) == exp

    def test_parse_repo_params_pass_keys(self):
        url = "copr://foo/bar?param1=foo&param2=bar&param3=baz&param4=qux"
        supported = ["param1", "param2", "param4"]
        expected = {"param1": "foo", "param2": "bar", "param4": "qux"}
        assert parse_repo_params(url, supported_keys=supported) == expected

    def test_subdir_match(self):
        assert SubdirMatch(None).match("a") == True
        assert SubdirMatch("").match("a") == True
        assert SubdirMatch("").match("") == False
        assert SubdirMatch("a").match("") == False
        assert SubdirMatch("a").match("a") == False
        assert SubdirMatch("/a/").match("a") == False
        assert SubdirMatch("//a/../a/").match("./a/b") == True
        assert SubdirMatch("//a/../a/").match("a/b") == True
        assert SubdirMatch("//a/../a/").match("a/b") == True
        assert SubdirMatch("//a/../a/").match("././a/b") == True

    def test_raw_patch_parse(self):
        workdir = os.path.dirname(__file__)
        def changes(filename):
            full = os.path.join(workdir, filename)
            with open(full) as f:
                return raw_commit_changes(f.read())

        assert changes('data/webhooks/raw-01.patch') == set([
            'frontend/coprs_frontend/coprs/forms.py',
            'frontend/coprs_frontend/coprs/static/css/custom-styles.css',
            'frontend/coprs_frontend/coprs/templates/_helpers.html'
        ])

        assert changes('data/webhooks/raw-02.patch') == set([
            'frontend/coprs_frontend/coprs/models.py',
            'frontend/coprs_frontend/alembic/schema/versions/code4beaf000_add_indexes3.py',
        ])

    def test_pagure_html_diff_parser(self):
        workdir = os.path.dirname(__file__)
        def changes(filename):
            full = os.path.join(workdir, filename)
            with open(full) as f:
                return pagure_html_diff_changed(f.read())

        assert changes('data/webhooks/diff-01.html') == set([
            'frontend/coprs_frontend/alembic/schema/versions/8ae65946df53_add_blocked_by_column_for_batch.py',
            'frontend/coprs_frontend/coprs/logic/builds_logic.py',
            'frontend/coprs_frontend/coprs/logic/modules_logic.py',
            'frontend/coprs_frontend/coprs/models.py',
            'frontend/coprs_frontend/coprs/views/backend_ns/backend_general.py'
        ])

        assert changes('data/webhooks/diff-02.html') == set([
            'frontend/coprs_frontend/alembic/schema/versions/code4beaf000_add_indexes3.py',
            'frontend/coprs_frontend/coprs/models.py',
        ])

        assert changes('data/webhooks/diff-03.html') == set([])
        assert changes('data/webhooks/diff-04.html') == set([
            '.gitignore',
            'copr-backend.spec',
            'sources',
        ])

        # Check that we don't traceback.
        assert pagure_html_diff_changed(None) == set([])
        assert pagure_html_diff_changed(1) == set([])
        assert pagure_html_diff_changed('<html') == set([])
        assert pagure_html_diff_changed('<html></html>') == set([])
        assert pagure_html_diff_changed('some-dust-ajablůňka>isdf/#~<--') == set([])
        assert pagure_html_diff_changed(b'091213114151deadbeaf') == set([])
