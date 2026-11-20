import re


def _slugify(text):
    # same rules as posts._slugify
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text)
    return text.strip("-")


def tag_index(posts):
    """Map tag slug -> sorted post slugs. posts: list of (Post, [tag names])."""
    index = {}
    for post, tags in posts:
        for tag in tags:
            index.setdefault(_slugify(tag), []).append(post.slug)
    return {k: sorted(v) for k, v in index.items()}
