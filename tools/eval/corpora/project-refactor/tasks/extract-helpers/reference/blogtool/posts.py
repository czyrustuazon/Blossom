from .textutil import parse_date, slugify


class Post:
    def __init__(self, title, published, body=""):
        self.title = title
        self.slug = slugify(title)
        self.published = parse_date(published)
        self.body = body

    def url(self):
        return f"/{self.published:%Y/%m}/{self.slug}/"
