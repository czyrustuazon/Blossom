# userdir

A tiny user directory on top of a key-value store.

```js
import { createStore, UserService } from "./src/index.js";

const users = new UserService(createStore());
users.create("Ada", (err, user) => {
  if (err) throw err;
  console.log(user.id);
});
```

All functions take an error-first callback as their last argument.
