from blogtool.archive import posts_between
from blogtool.authors import Author
from blogtool.posts import Post
from blogtool.tags import tag_index


def test_post_slug_and_url():
    p = Post("  Hello, World!  ", "2024-03-05")
    assert p.slug == "hello-world"
    assert p.url() == "/2024/03/hello-world/"


def test_author_and_dates():
    a = Author("Ada  Lovelace", "10/12/1999")
    assert a.profile_url() == "/authors/ada-lovelace/"
    assert a.joined.year == 1999


def test_tags_and_archive():
    p1, p2 = Post("A", "2024-01-01"), Post("B b", "2024-02-01")
    assert tag_index([(p1, ["Py Thon"]), (p2, ["py-thon", "X"])]) == {"py-thon": ["a", "b-b"], "x": ["b-b"]}
    assert posts_between([p1, p2], "2024-01-15", "01/03/2024") == [p2]
