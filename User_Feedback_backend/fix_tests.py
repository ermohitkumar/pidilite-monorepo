import re
import os

fixes = {
    "test_create_keyword_duplicate": 409,
    "test_update_keyword_not_found": 404,
    "test_delete_keyword_not_found": 404,
    "test_get_registry_invalid_key": 400,
    "test_add_item_duplicate": 409,
    "test_add_item_invalid_key": 400,
    "test_rename_item_not_found": 404,
    "test_rename_item_conflict": 409,
    "test_rename_item_invalid_key": 400,
    "test_delete_item_not_found": 404,
    "test_delete_item_invalid_key": 400,
    "test_sso_unregistered_user": 401,
    "test_sso_inactive_user": 403,
    "test_create_user_duplicate_email": 409,
    "test_create_user_weak_password": 422,
    "test_get_profile_forbidden": 403,
    "test_get_profile_not_found": 404,
    "test_update_user_not_found": 404,
    "test_delete_user_not_found": 404,
}

test_dir = "/Users/akshaymanjunath/pidilite/tests"

for root, _, files in os.walk(test_dir):
    for file in files:
        if file.endswith(".py"):
            filepath = os.path.join(root, file)
            with open(filepath, "r") as f:
                content = f.read()

            # Find all function definitions
            for test_name, expected_status in fixes.items():
                # We look for the function block and replace `res.status_code == 200` with `res.status_code == expected_status`
                pattern = r"(def " + test_name + \
                    r"\(.*?\):.*?)(?=\n    def |\Z)"
                match = re.search(pattern, content, re.DOTALL)
                if match:
                    block = match.group(1)
                    new_block = re.sub(r"assert res\.status_code == 200",
                                       f"assert res.status_code == {expected_status}", block)
                    content = content.replace(block, new_block)

            with open(filepath, "w") as f:
                f.write(content)

print("Fixed tests")
