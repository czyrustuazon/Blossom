# userdir

A tiny user directory on top of a key-value store.

```js
import { createStore, UserService } from "./src/index.js";

const users = new UserService(createStore());
const user = await users.create("Ada");
console.log(user.id);
```

All functions return promises.
