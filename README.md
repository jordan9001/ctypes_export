# ctypes Export
Author: **Jordan Whitehead**

_This plugin exports ctypes definitions for given structures._

## Description:
Attempts to export specified types to python ctypes definitions, along with enums. It can gather and define all the dependent types as well.

It currently sometimes chokes on order with circular dependencies, and you may have to move some of the definitions to make the python valid.

## License

This plugin is released under an [MIT license](./LICENSE).
