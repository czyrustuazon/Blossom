class OutboxTransport:
    """Records messages instead of sending them. Fails the first `fail_times` sends."""

    def __init__(self, fail_times=0):
        self.sent = []
        self.fail_times = fail_times

    def send(self, channel, to, body):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("transient")
        self.sent.append((channel, to, body))
