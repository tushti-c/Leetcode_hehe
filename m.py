import os
import re
import json
import time
import html
import requests
from pathlib import Path
from requests.exceptions import HTTPError

print("STARTING SCRIPT")

BASE_DIR = Path("leetcode_easy")
BASE_DIR.mkdir(exist_ok=True)

GRAPHQL_URL = "https://leetcode.com/graphql"

SESSION = requests.Session()
SESSION.headers.update({
    "Content-Type": "application/json",
    "Referer": "https://leetcode.com",
    "User-Agent": "Mozilla/5.0"
})

# -----------------------------
# Config
# -----------------------------
LANG_SLUG = "java"
LIMIT = 20          # how many easy questions to download
SKIP_PAID = True    # skip premium-only questions
SLEEP_SECS = 0.5    # be polite


# -----------------------------
# Helpers
# -----------------------------
def slug_to_folder_name(frontend_id: str, title_slug: str) -> str:
    return f"{str(frontend_id).zfill(4)}_{title_slug.replace('-', '_')}"


def safe_markdown_from_html(html_text: str) -> str:
    # Simple HTML cleanup for markdown-ish output
    text = html.unescape(html_text)

    replacements = [
        (r"<pre>", "\n```text\n"),
        (r"</pre>", "\n```\n"),
        (r"<code>", "`"),
        (r"</code>", "`"),
        (r"<strong>|<b>", "**"),
        (r"</strong>|</b>", "**"),
        (r"<em>|<i>", "*"),
        (r"</em>|</i>", "*"),
        (r"<li>", "- "),
        (r"</li>", "\n"),
        (r"<br\s*/?>", "\n"),
        (r"</p>", "\n\n"),
        (r"<p>", ""),
        (r"</h1>|</h2>|</h3>|</h4>", "\n\n"),
        (r"<h1>", "# "),
        (r"<h2>", "## "),
        (r"<h3>", "### "),
        (r"<h4>", "#### "),
        (r"</ul>|</ol>", "\n"),
        (r"<ul>|<ol>", "\n"),
    ]

    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def graphql(query: str, variables: dict) -> dict:
    operation_match = re.search(r"query\s+([A-Za-z0-9_]+)", query)
    payload = {"query": query, "variables": variables}
    if operation_match:
        payload["operationName"] = operation_match.group(1)

    resp = SESSION.post(GRAPHQL_URL, json=payload, timeout=30)

    try:
        resp.raise_for_status()
    except HTTPError as exc:
        body = resp.text.strip()
        snippet = body[:500] + ("..." if len(body) > 500 else "")
        raise RuntimeError(
            f"GraphQL HTTP {resp.status_code} for {payload.get('operationName', 'unknown operation')}: {snippet}"
        ) from exc

    data = resp.json()

    if "errors" in data:
        raise RuntimeError(f"GraphQL error: {data['errors']}")

    return data["data"]


# -----------------------------
# Query 1: list easy problems
# -----------------------------
PROBLEMSET_QUERY = """
query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
  problemsetQuestionList: questionList(
    categorySlug: $categorySlug
    limit: $limit
    skip: $skip
    filters: $filters
  ) {
    total: totalNum
    questions: data {
      questionFrontendId
      title
      titleSlug
      difficulty
      isPaidOnly
      topicTags {
        name
        slug
      }
    }
  }
}
"""

# -----------------------------
# Query 2: get full question details
# -----------------------------
QUESTION_DETAIL_QUERY = """
query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    questionId
    questionFrontendId
    title
    titleSlug
    content
    difficulty
    isPaidOnly
    hints
    exampleTestcaseList
    topicTags {
      name
      slug
    }
    codeSnippets {
      lang
      langSlug
      code
    }
  }
}
"""


def fetch_easy_questions(limit: int):
    questions = []
    skip = 0
    batch_size = 50

    while len(questions) < limit:
        data = graphql(
            PROBLEMSET_QUERY,
            {
                "categorySlug": "",
                "limit": batch_size,
                "skip": skip,
                "filters": {"difficulty": "EASY"}
            }
        )

        batch = data["problemsetQuestionList"]["questions"]
        if not batch:
            break

        for q in batch:
            if SKIP_PAID and q["isPaidOnly"]:
                continue
            questions.append(q)
            if len(questions) >= limit:
                break

        skip += batch_size
        time.sleep(SLEEP_SECS)

    return questions


def fetch_question_detail(title_slug: str):
    data = graphql(QUESTION_DETAIL_QUERY, {"titleSlug": title_slug})
    return data["question"]


def build_readme(question: dict) -> str:
    title = question["title"]
    qid = question["questionFrontendId"]
    difficulty = question["difficulty"]
    url = f"https://leetcode.com/problems/{question['titleSlug']}/description/"
    tags = ", ".join(tag["name"] for tag in question.get("topicTags", [])) or "None"
    hints = question.get("hints") or []
    body_md = safe_markdown_from_html(question.get("content") or "")

    hint_section = ""
    if hints:
        hint_section = "## Hints\n\n" + "\n".join(f"- {h}" for h in hints) + "\n\n"

    return f"""# {qid}. {title}

**Difficulty:** {difficulty}  
**URL:** {url}  
**Tags:** {tags}

## Problem

{body_md}

{hint_section}""".strip() + "\n"


def get_code_stub(question: dict, lang_slug: str) -> str:
    for snippet in question.get("codeSnippets", []):
        if snippet["langSlug"] == lang_slug:
            return snippet["code"]
    return "// No code snippet found for selected language.\n"


def build_test_file(question: dict) -> str:
    tests = question.get("exampleTestcaseList") or []
    if not tests:
        return "No example test cases found.\n"

    lines = []
    for i, test in enumerate(tests, start=1):
        lines.append(f"Example {i}")
        lines.append("-" * 20)
        lines.append(test.strip())
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_question_files(question: dict):
    folder_name = slug_to_folder_name(question["questionFrontendId"], question["titleSlug"])
    problem_dir = BASE_DIR / folder_name
    problem_dir.mkdir(parents=True, exist_ok=True)

    readme_path = problem_dir / "README.md"
    solution_path = problem_dir / "solution.java"
    tests_path = problem_dir / "test_cases.txt"

    readme_path.write_text(build_readme(question), encoding="utf-8")
    solution_path.write_text(get_code_stub(question, LANG_SLUG), encoding="utf-8")
    tests_path.write_text(build_test_file(question), encoding="utf-8")


def main():
    easy_questions = fetch_easy_questions(LIMIT)
    print(f"Found {len(easy_questions)} easy questions")

    for i, q in enumerate(easy_questions, start=1):
        slug = q["titleSlug"]
        print(f"[{i}/{len(easy_questions)}] Fetching {slug}...")
        detail = fetch_question_detail(slug)
        write_question_files(detail)
        time.sleep(SLEEP_SECS)

    print(f"\nDone. Files saved under: {BASE_DIR.resolve()}")


if __name__ == "__main__":
    main()
