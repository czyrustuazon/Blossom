from .textutil import slugify


def tag_index(posts):
    """Map tag slug -> sorted post slugs. posts: list of (Post, [tag names])."""
    index = {}
    for post, tags in posts:
        for tag in tags:
            index.setdefault(slugify(tag), []).append(post.slug)
    return {k: sorted(v) for k, v in index.items()}
