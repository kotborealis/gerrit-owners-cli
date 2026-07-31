from gerrit_owners_cli.cli import (
    _parse_response,
    build_account_url,
    build_api_url,
    extract_account_ids,
    extract_owner_groups,
    format_owner_summary,
)


def test_build_api_url_quotes_project_branch_and_path():
    assert build_api_url(
        "gerrit.example.com",
        "example/project",
        "refs/heads/master",
        "toolchain/host_toolchain/elements/3rd_party/expat.bst",
    ) == (
        "https://gerrit.example.com/a/projects/example%2Fproject/"
        "branches/refs%2Fheads%2Fmaster/code_owners/"
        "toolchain%2Fhost_toolchain%2Felements%2F3rd_party%2Fexpat.bst"
    )


def test_build_account_url_quotes_account_id():
    assert build_account_url("gerrit.example.com", 42) == (
        "https://gerrit.example.com/a/accounts/42"
    )


def test_parse_response_removes_gerrit_xssi_prefix():
    assert _parse_response(")]}'\n{\"code_owners\": []}") == {"code_owners": []}


def test_extract_owner_groups_flattens_nested_imports_and_deduplicates():
    response = {
        "code_owner_configs": [
            {
                "imports": [
                    {
                        "project": "example/project",
                        "path": "/groups/platform-team",
                        "imports": [
                            {
                                "project": "example/tools",
                                "path": "/groups/tooling-team",
                            }
                        ],
                    },
                    {
                        "project": "example/tools",
                        "path": "/groups/tooling-team",
                    },
                ]
            }
        ]
    }
    assert extract_owner_groups(response) == [
        "example/project:/groups/platform-team",
        "example/tools:/groups/tooling-team",
    ]


def test_parse_response_keeps_all_gerrit_fields():
    response = _parse_response(
        ")]}'\n"
        '{"code_owners":[{"account":{"_account_id":42}}],'
        '"code_owner_configs":[]}'
    )
    assert response == {
        "code_owners": [{"account": {"_account_id": 42}}],
        "code_owner_configs": [],
    }


def test_extract_account_ids_deduplicates_accounts():
    response = {
        "code_owners": [
            {"account": {"_account_id": 42}},
            {"account": {"_account_id": 42}},
            {"account": {"_account_id": 43}},
        ]
    }
    assert extract_account_ids(response) == [42, 43]


def test_format_owner_summary_omits_scoring():
    response = {
        "code_owner_configs": [
            {"imports": [{"project": "example/tools", "path": "/groups/tooling-team"}]}
        ]
    }
    assert format_owner_summary(
        response,
        [{"_account_id": 42, "name": "Example User", "email": "user@example.com"}],
    ) == ("Owner groups:\n- example/tools:/groups/tooling-team\n\nCode owners:\n"
          "- Example User <user@example.com>")
