import base64
import json
import os
import time
from functools import wraps
import datetime
import uuid

import pytest
import decorator

import coprs

from copr_common.enums import ActionTypeEnum, BackendResultEnum, StatusEnum
from coprs import helpers
from coprs import models
from coprs import cache
from coprs.logic.coprs_logic import BranchesLogic

from unittest import mock


class CoprsTestCase(object):

    original_config = coprs.app.config.copy()

    @classmethod
    def setup_class(cls):
        config = coprs.app.config
        for key in [
                "LOCAL_TMP_DIR",
                "STORAGE_DIR",
            ]:
            if key in config:
                path = os.path.abspath(config[key])
                if not os.path.exists(path):
                    os.makedirs(path)

    @classmethod
    def teardown_class(cls):
        config = coprs.app.config
        # TODO: some tests fails with this cleanup - investigate and fix
        # if "LOCAL_TMP_DIR" in config:
        #    shutil.rmtree(os.path.abspath(config["LOCAL_TMP_DIR"]))

    def setup_method(self, method):
        self.tc = coprs.app.test_client()
        self.app = coprs.app
        self.app.testing = True
        self.db = coprs.db
        self.db.session = self.db.create_scoped_session()
        self.models = models
        self.helpers = helpers
        self.backend_passwd = coprs.app.config["BACKEND_PASSWORD"]
        # create datadir if it doesn't exist
        # datadir = os.path.commonprefix(
        #    [self.app.config["DATABASE"], self.app.config["OPENID_STORE"]])
        # if not os.path.exists(datadir):
        #    os.makedirs(datadir)
        coprs.db.create_all()
        self.db.session.commit()
        #coprs/views/coprs_ns/coprs_general.py
        self.rmodel_TSE_coprs_general_patcher = mock.patch("coprs.views.coprs_ns.coprs_general.TimedStatEvents")
        self.rmodel_TSE_coprs_general_mc = self.rmodel_TSE_coprs_general_patcher.start()
        self.rmodel_TSE_coprs_general_mc.return_value.get_count.return_value = 0
        self.rmodel_TSE_coprs_general_mc.return_value.add_event.return_value = None

    def teardown_method(self, method):
        # delete just data, not the tables
        self.db.session.rollback()
        for tbl in reversed(self.db.metadata.sorted_tables):
            self.db.engine.execute(tbl.delete())

        self.rmodel_TSE_coprs_general_patcher.stop()
        self.app.config = self.original_config.copy()
        cache.clear()

    @property
    def auth_header(self):
        return {"Authorization": b"Basic " +
                base64.b64encode("doesntmatter:{0}".format(self.backend_passwd).encode("utf-8"))}

    @pytest.fixture
    def f_db(self):
        self.db.session.commit()

    @pytest.fixture
    def f_users(self):
        self.u1 = models.User(
            username=u"user1",
            proven=False,
            admin=True,
            mail="user1@foo.bar")

        self.u2 = models.User(
            username=u"user2",
            proven=False,
            mail="user2@spam.foo")

        self.u3 = models.User(
            username=u"user3",
            proven=False,
            mail="baz@bar.bar")

        self.basic_user_list = [self.u1, self.u2, self.u3]

        self.db.session.add_all(self.basic_user_list)

    @pytest.fixture
    def f_fas_groups(self, f_users):
        self.fas_group_names = [
            "fas_1",
            "fas_2",
            "fas_3",
            "fas_4",
        ]
        self.u1.openid_groups = {'fas_groups': self.fas_group_names[:2]}
        self.db.session.add(self.u1)

        return self.fas_group_names

    @pytest.fixture
    def f_users_api(self):
        """
        Requires f_users
        """
        self.user_api_creds = {}
        for idx, u in enumerate([self.u1, self.u2, self.u3]):
            u.api_login = "foo_{}".format(idx)
            u.api_token = "bar_{}".format(idx)

            u.api_token_expiration = datetime.date.today() + datetime.timedelta(days=1000)
            self.user_api_creds[u.username] = {"login": u.api_login, "token": u.api_token}

    @pytest.fixture
    def f_coprs(self):
        self.c1 = models.Copr(name=u"foocopr", user=self.u1, repos="")
        self.c2 = models.Copr(name=u"foocopr", user=self.u2, repos="")
        self.c3 = models.Copr(name=u"barcopr", user=self.u2, repos="")
        self.basic_coprs_list = [self.c1, self.c2, self.c3]
        self.db.session.add_all(self.basic_coprs_list)

        self.c1_dir = models.CoprDir(name=u"foocopr", copr=self.c1, main=True)
        self.c2_dir = models.CoprDir(name=u"foocopr", copr=self.c2, main=True)
        self.c3_dir = models.CoprDir(name=u"barcopr", copr=self.c3, main=True)
        self.basic_copr_dir_list = [self.c1_dir, self.c2_dir, self.c3_dir]
        self.db.session.add_all(self.basic_copr_dir_list)

    @pytest.fixture
    def f_mock_chroots(self):
        self.mc1 = models.MockChroot(
            os_release="fedora", os_version="18", arch="x86_64", is_active=True)
        self.mc1.distgit_branch = models.DistGitBranch(name='f18')

        self.mc2 = models.MockChroot(
            os_release="fedora", os_version="17", arch="x86_64", is_active=True,
            comment="A short chroot comment")
        self.mc2.distgit_branch = models.DistGitBranch(name='fedora-17')

        self.mc3 = models.MockChroot(
            os_release="fedora", os_version="17", arch="i386", is_active=True,
            comment="Chroot comment containing <a href='https://copr.fedorainfracloud.org/'>url with four words</a>")
        self.mc3.distgit_branch = self.mc2.distgit_branch

        self.mc4 = models.MockChroot(
            os_release="fedora", os_version="rawhide", arch="i386", is_active=True)
        self.mc4.distgit_branch = models.DistGitBranch(name='master')

        self.mc_basic_list = [self.mc1, self.mc2, self.mc3, self.mc4]
        # only bind to coprs if the test has used the f_coprs fixture
        if hasattr(self, "c1"):
            cc1 = models.CoprChroot()
            cc1.mock_chroot = self.mc1
            # c1 foocopr with fedora-18-x86_64
            self.c1.copr_chroots.append(cc1)

            cc2 = models.CoprChroot()
            cc2.mock_chroot = self.mc2
            cc3 = models.CoprChroot()
            cc3.mock_chroot = self.mc3
            # c2 foocopr with fedora-17-i386 fedora-17-x86_64
            self.c2.copr_chroots.append(cc2)
            self.c2.copr_chroots.append(cc3)

            cc4 = models.CoprChroot()
            cc4.mock_chroot = self.mc4
            # c3 barcopr with fedora-rawhide-i386
            self.c3.copr_chroots.append(cc4)
            self.db.session.add_all([cc1, cc2, cc3, cc4])

        self.db.session.add_all([self.mc1, self.mc2, self.mc3, self.mc4])

    @pytest.fixture
    def f_mock_chroots_many(self):
        """
        Adds more chroots to self.c1
        Requires: f_mock_chroots
        """
        self.mc_list = []
        for arch in ["x86_64", "i386"]:
            for os_version in range(19, 24):
                mc = models.MockChroot(
                    os_release="fedora", os_version=os_version,
                    arch=arch, is_active=True)
                # Let's try slashes now. for example.  Some copr instances use
                # this pattern.
                mc.distgit_branch = BranchesLogic.get_or_create(
                        'fedora/{0}'.format(os_version),
                        session=self.db.session)
                self.mc_list.append(mc)

            for os_version in [5, 6, 7]:
                mc = models.MockChroot(
                    os_release="epel", os_version=os_version,
                    arch=arch, is_active=True)
                mc.distgit_branch = BranchesLogic.get_or_create(
                        'el{0}'.format(os_version),
                        session=self.db.session)
                self.mc_list.append(mc)

        self.mc_list[-1].is_active = False

        # only bind to coprs if the test has used the f_coprs fixture
        if hasattr(self, "c1"):
            for mc in self.mc_list:
                cc = models.CoprChroot()
                cc.mock_chroot = mc
                # TODO: why 'self.c1.copr_chroots.append(cc)' doesn't work here?
                cc.copr = self.c1

        self.db.session.add_all(self.mc_list)

    @pytest.fixture
    def f_builds(self):
        self.p1 = models.Package(
            copr=self.c1, copr_dir=self.c1_dir, name="hello-world", source_type=0)
        self.p2 = models.Package(
            copr=self.c2, copr_dir=self.c2_dir, name="whatsupthere-world", source_type=0)
        self.p3 = models.Package(
            copr=self.c2, copr_dir=self.c3_dir, name="goodbye-world", source_type=0)

        self.b1 = models.Build(
            copr=self.c1, copr_dir=self.c1_dir, package=self.p1,
            user=self.u1, submitted_on=50, srpm_url="http://somesrpm",
            source_status=StatusEnum("succeeded"), result_dir='bar')
        self.b2 = models.Build(
            copr=self.c1, copr_dir=self.c1_dir, package=self.p1,
            user=self.u2, submitted_on=10, srpm_url="http://somesrpm",
            source_status=StatusEnum("importing"), result_dir='bar',
            source_json='{}')
        self.b3 = models.Build(
            copr=self.c2, copr_dir=self.c2_dir, package=self.p2, user=self.u2, submitted_on=10, srpm_url="http://somesrpm", source_status=StatusEnum("importing"), result_dir='bar')
        self.b4 = models.Build(
            copr=self.c2, copr_dir=self.c2_dir, package=self.p2, user=self.u2, submitted_on=100, srpm_url="http://somesrpm", source_status=StatusEnum("succeeded"), result_dir='bar')

        self.basic_builds = [self.b1, self.b2, self.b3, self.b4]
        self.b1_bc = []
        self.b2_bc = []
        self.b3_bc = []
        self.b4_bc = []

        for build, build_chroots in zip(
                [self.b1, self.b2, self.b3, self.b4],
                [self.b1_bc, self.b2_bc, self.b3_bc, self.b4_bc]):

            status = None
            if build is self.b1:  # this build is going to be deleted
                status = StatusEnum("succeeded")
            for chroot in build.copr.active_chroots:
                buildchroot = models.BuildChroot(
                    build=build,
                    mock_chroot=chroot,
                    status=status,
                    git_hash="12345",
                    result_dir='bar',
                )

                if build is self.b1 or build is self.b2:
                    buildchroot.started_on = 1390866440
                    buildchroot.ended_on = 1490866440


                build_chroots.append(buildchroot)
                self.db.session.add(buildchroot)

        self.db.session.add_all([self.b1, self.b2, self.b3, self.b4])

    @pytest.fixture
    def f_fork_prepare(self, f_coprs, f_mock_chroots, f_builds):

        self.p4 = models.Package(
            copr=self.c2, copr_dir=self.c2_dir, name="hello-world", source_type=0)
        self.b5 = models.Build(
            copr=self.c2, copr_dir=self.c2_dir, package=self.p4,
            user=self.u1, submitted_on=50, srpm_url="http://somesrpm",
            source_status=StatusEnum("succeeded"), result_dir='00000005-hello-world')
        self.b6 = models.Build(
            copr=self.c2, copr_dir=self.c2_dir, package=self.p4,
            user=self.u1, submitted_on=10, srpm_url="http://somesrpm",
            source_status=StatusEnum("failed"), result_dir='00000006-hello-world',
            source_json='{}')
        self.b7 = models.Build(
            copr=self.c2, copr_dir=self.c2_dir, package=self.p2,
            user=self.u1, submitted_on=10, srpm_url="http://somesrpm",
            source_status=StatusEnum("succeeded"), result_dir='00000007-whatsupthere-world')
        self.b8 = models.Build(
            copr=self.c2, copr_dir=self.c2_dir, package=self.p2,
            user=self.u1, submitted_on=100, srpm_url="http://somesrpm",
            source_status=StatusEnum("succeeded"), result_dir='00000008-whatsupthere-world')

        self.basic_builds = [self.b5, self.b6, self.b7, self.b8]
        self.b5_bc = []
        self.b6_bc = []
        self.b7_bc = []
        self.b8_bc = []
        self.db.session.flush()

        for build, build_chroots in zip(
                [self.b5, self.b6, self.b7, self.b8],
                [self.b5_bc, self.b6_bc, self.b7_bc, self.b8_bc]):

            status = StatusEnum("succeeded")
            for chroot in build.copr.active_chroots:
                buildchroot = models.BuildChroot(
                    build=build,
                    mock_chroot=chroot,
                    status=status,
                    git_hash="12345",
                    result_dir="{}-{}".format(build.id, build.package.name),
                )
                build_chroots.append(buildchroot)
                self.db.session.add(buildchroot)
        self.db.session.add_all([self.b5, self.b6, self.b7, self.b8])

        self.p5 = models.Package(
            copr=self.c2, copr_dir=self.c2_dir, name="new-package", source_type=0)
        self.b9 = models.Build(
            copr=self.c2, copr_dir=self.c2_dir, package=self.p5,
            user=self.u1, submitted_on=100, srpm_url="http://somesrpm",
            source_status=StatusEnum("succeeded"), result_dir='00000009-new-package')
        self.b10 = models.Build(
            copr=self.c2, copr_dir=self.c2_dir, package=self.p5,
            user=self.u1, submitted_on=100, srpm_url="http://somesrpm",
            source_status=StatusEnum("failed"), result_dir='00000010-new-package')
        self.b11 = models.Build(
            copr=self.c2, copr_dir=self.c2_dir, package=self.p5,
            user=self.u1, submitted_on=100, srpm_url="http://somesrpm",
            source_status=StatusEnum("failed"), result_dir='00000011-new-package')

        self.b9_bc = []
        self.b10_bc = []
        self.b11_bc = []
        self.db.session.flush()

        bc_status = {self.b9: {self.mc2: StatusEnum("succeeded"),
                               self.mc3: StatusEnum("succeeded")},
                     self.b10: {self.mc2: StatusEnum("forked"),
                                self.mc3: StatusEnum("failed")},
                     self.b11: {self.mc2: StatusEnum("failed"),
                                self.mc3: StatusEnum("succeeded")}}

        for build, build_chroots in zip(
                [self.b9, self.b10, self.b11],
                [self.b9_bc, self.b10_bc, self.b11_bc]):

            for chroot in build.copr.active_chroots:
                buildchroot = models.BuildChroot(
                    build=build,
                    mock_chroot=chroot,
                    status=bc_status[build][chroot],
                    git_hash="12345",
                    result_dir="{}-{}".format(build.id, build.package.name),
                )
                build_chroots.append(buildchroot)
                self.db.session.add(buildchroot)
        self.db.session.add_all([self.b9, self.b10, self.b11])

    @pytest.fixture
    def f_hook_package(self, f_users, f_coprs, f_mock_chroots, f_builds):
        self.c1.webhook_secret = str(uuid.uuid4())
        self.db.session.add(self.c1)
        self.pHook = models.Package(
            copr=self.c1,
            copr_dir=self.c1_dir,
            name="hook-package",
            source_type=helpers.BuildSourceEnum('scm'))

    @pytest.fixture
    def f_build_few_chroots(self, f_mock_chroots_many):
        """
            Requires fixture: f_mock_chroots_many
        """
        self.b_few_chroots = models.Build(
            id=2345,
            copr=self.c1,
            copr_dir=self.c1_dir,
            user=self.u1,
            submitted_on=50,
            pkgs="http://example.com/copr-keygen-1.58-1.fc20.src.rpm",
            pkg_version="1.58"
        )

        self.db.session.add(self.b_few_chroots)
        self.status_by_chroot = {
            'epel-5-i386': 0,
            'fedora-20-i386': 1,
            'fedora-20-x86_64': 1,
            'fedora-21-i386': 1,
            'fedora-21-x86_64': 4
        }

        for chroot in self.b_few_chroots.copr.active_chroots:
            if chroot.name in self.status_by_chroot:
                buildchroot = models.BuildChroot(
                    build=self.b_few_chroots,
                    mock_chroot=chroot,
                    status=self.status_by_chroot[chroot.name],
                    git_hash="12345",
                    result_dir='bar',
                )
                self.db.session.add(buildchroot)

        self.db.session.add(self.b_few_chroots)

    @pytest.fixture
    def f_build_many_chroots(self):
        """
            Requires: f_mock_chroots_many
        """
        self.b_many_chroots = models.Build(
            id=12347,
            copr=self.c1,
            copr_dir=self.c1_dir,
            user=self.u1,
            submitted_on=50,
            pkgs="http://example.com/copr-keygen-1.58-1.fc20.src.rpm",
            pkg_version="1.58"
        )

        self.db.session.add(self.b_many_chroots)
        self.status_by_chroot = {
            'epel-5-i386': 0,
            'epel-5-x86_64': 1,
            'epel-6-i386': 0,
            'epel-6-x86_64': 3,
            'epel-7-x86_64': 4,
            'fedora-18-x86_64': 5,
            'fedora-19-i386': 5,
            'fedora-19-x86_64': 6,
            'fedora-20-i386': 2,
            'fedora-20-x86_64': 3,
            'fedora-21-i386': 0,
            'fedora-21-x86_64': 0,
            'fedora-22-i386': 1,
            'fedora-22-x86_64': 1,
            'fedora-23-i386': 1,
            'fedora-23-x86_64': 4,
        }

        for chroot in self.b_many_chroots.copr.active_chroots:
            buildchroot = models.BuildChroot(
                build=self.b_many_chroots,
                mock_chroot=chroot,
                status=self.status_by_chroot[chroot.name],
                git_hash="12345",
                result_dir='bar',
            )
            self.db.session.add(buildchroot)

        self.db.session.add(self.b_many_chroots)

    @pytest.fixture
    def f_copr_permissions(self):
        self.cp1 = models.CoprPermission(
            copr=self.c2,
            user=self.u1,
            copr_builder=helpers.PermissionEnum("approved"),
            copr_admin=helpers.PermissionEnum("nothing"))

        self.cp2 = models.CoprPermission(
            copr=self.c3,
            user=self.u3,
            copr_builder=helpers.PermissionEnum("nothing"),
            copr_admin=helpers.PermissionEnum("nothing"))

        self.cp3 = models.CoprPermission(
            copr=self.c3,
            user=self.u1,
            copr_builder=helpers.PermissionEnum("request"),
            copr_admin=helpers.PermissionEnum("approved"))


    @pytest.fixture
    def f_copr_more_permissions(self, f_copr_permissions):
        self.u4 = models.User(
            username=u"user4",
            proven=False,
            mail="baasdfz@bar.bar",
            api_token='u4xxx',
            api_login='u4login',
            api_token_expiration=datetime.date.today() + datetime.timedelta(days=1000))

        # only a builder
        self.cp4 = models.CoprPermission(
            copr=self.c3,
            user=self.u4,
            copr_builder=helpers.PermissionEnum("approved"),
            copr_admin=helpers.PermissionEnum("nothing"))

        self.db.session.add_all([self.cp1, self.cp2, self.cp3])

    @pytest.fixture
    def f_actions(self, f_db):
        self.delete_action = models.Action(action_type=ActionTypeEnum("delete"),
                                           object_type="copr",
                                           object_id=self.c1.id,
                                           old_value="asd/qwe",
                                           new_value=None,
                                           result=BackendResultEnum("waiting"),
                                           created_on=int(time.time()))
        self.cancel_build_action = models.Action(action_type=ActionTypeEnum("cancel_build"),
                                                 data=json.dumps({'task_id': 123}),
                                                 result=BackendResultEnum("waiting"),
                                                 created_on=int(time.time()))
        self.db.session.add_all([self.delete_action, self.cancel_build_action])

    @pytest.fixture
    def f_modules(self):
        self.m1 = models.Module(name="first-module", stream="foo", version=1, copr_id=self.c1.id, copr=self.c1,
                                summary="Sum 1", description="Desc 1", created_on=time.time())
        self.m2 = models.Module(name="second-module", stream="bar", version=3, copr_id=self.c1.id, copr=self.c1,
                                summary="Sum 2", description="Desc 2", created_on=time.time())
        self.m3 = models.Module(name="third-module", stream="baz", version=1, copr_id=self.c2.id, copr=self.c2,
                                summary="Sum 3", description="Desc 3", created_on=time.time())
        self.db.session.add_all([self.m1, self.m2, self.m3])

    @pytest.fixture
    def f_pr_dir(self):
        self.c4_dir = models.CoprDir(name=u"foocopr:PR", copr=self.c1,
                main=False)
        self.p4 = models.Package(
            copr=self.c1, copr_dir=self.c4_dir, name="hello-world",
            source_type=0)

    @pytest.fixture
    def f_batches(self):
        self.batch1 = models.Batch()
        self.batch2 = models.Batch()
        self.batch3 = models.Batch()
        self.batch4 = models.Batch()

    def request_rest_api_with_auth(self, url,
                                   login=None, token=None,
                                   content=None, method="GET",
                                   headers=None, data=None,
                                   content_type="application/json"):
        """
        :rtype: flask.wrappers.Response
        Requires f_users_api fixture
        """
        if login is None:
            login = self.user_api_creds["user1"]["login"]
        if token is None:
            token = self.user_api_creds["user1"]["token"]

        req_headers = {
            "Authorization": self._get_auth_string(login, token),
        }
        if headers:
            req_headers.update(headers)

        kwargs = dict(
            method=method,
            content_type=content_type,
            headers=req_headers,
            buffered=True,
        )
        if content is not None and data is not None:
            raise RuntimeError("Don't specify content and data together")

        if content:
            kwargs["data"] = json.dumps(content)
        if data:
            kwargs["data"] = data

        return self.tc.open(url, **kwargs)

    def _get_auth_string(self, login, token):
        userstring = "{}:{}".format(login, token).encode("utf-8")
        base64string_user = base64.b64encode(userstring)
        base64string = b"Basic " + base64string_user
        return base64string

    def post_api_with_auth(self, url, content, user):
        return self.tc.post(
            url,
            data=content,
            headers={
                "Authorization": self._get_auth_string(user.api_login, user.api_token)
            }
        )

    def api3_auth_headers(self, user):
        return {"Authorization": self._get_auth_string(user.api_login, user.api_token),
                "Content-Type": "application/json"}

    def post_api3_with_auth(self, url, content, user):
        headers = self.api3_auth_headers(user)
        return self.tc.post(url, data=json.dumps(content), headers=headers)

    def get_api3_with_auth(self, url, user):
        headers = self.api3_auth_headers(user)
        print(headers)
        return self.tc.get(url, headers=headers)


class TransactionDecorator(object):

    """
    This is decorator as a class.

    Its purpose is to replace repetative lines of 'with' statements
    in test's functions. Everytime you find your self writing test function
    which uses following 'with's construct:

    with self.tc as test_client:
        with c.session_transaction() as session:
            session['openid'] = self.u.username

    where 'u' stands for any user from 'f_users' fixture, use this to decorate
    your test function:

    @TransactionDecorator('u')
    def test_function_without_with_statements(self, f_users):
        # write code as you were in with 'self.tc as test_client' indent
        # you can also access object 'test_client' through 'self.test_client'

    where decorator parameter ''u'' stands for string representation of any
    user from 'f_users' fixture from which you wish to store 'username'.
    Please note that you **must** include 'f_users' fixture in decorated
    function parameters.

    """

    def __init__(self, user):
        self.user = user

    def __call__(self, fn):
        @wraps(fn)
        def wrapper(fn, fn_self, *args):
            username = getattr(fn_self, self.user).username
            with fn_self.tc as fn_self.test_client:
                with fn_self.test_client.session_transaction() as session:
                    session["openid"] = username
                return fn(fn_self, *args)
        return decorator.decorator(wrapper, fn)


def new_app_context(fn):
    """
    This is decorator function.  Use this anytime you need to run more than one
    'self.tc.{get,post,..}()' requests in one test, or when you see something
    like this in your test error output:
        E   sqlalchemy.orm.exc.DetachedInstanceError: Instance <..>
            is not bound to a Session; attribute refresh operation cannot
            proceed (Background on this error at: http://sqlalche.me/e/bhk3)
    For more info see
    https://stackoverflow.com/questions/19395697/sqlalchemy-session-not-getting-removed-properly-in-flask-testing
    """
    @wraps(fn)
    def wrapper(fn, fn_self, *args, **kwargs):
        with coprs.app.app_context():
            return fn(fn_self, *args, **kwargs)

    return decorator.decorator(wrapper, fn)
