from .textutil import parse_date, slugify


class Author:
    def __init__(self, name, joined):
        self.name = name
        self.handle = slugify(name)
        self.joined = parse_date(joined)

    def profile_url(self):
        return f"/authors/{self.handle}/"
