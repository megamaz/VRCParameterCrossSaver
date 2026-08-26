# Avatar Parameter Cross-Saver
This is a simple tool created for people who have a main avi, and who have their outfits separated between avis. You probably have some settings that are global (aka, shared across all avis regardless of outfit), and get annoyed when those settings get reset or set to the wrong value when swapping avis. Well, this tool aims to eliminate that, and saves those global settings across avi swaps.

## Requirements
- [Python](https://www.python.org/downloads/) 3.13 or above

## Usage
1. Run the `setup.bat`. This will download necessary dependencies for the project to function.
2. Once that's done, double-click the `main.pyw`.
3. I hope the UI is intuitive enough that I don't have to explain it.

## Note on VRCFury Parameters
You'll notice that VRCFury parameters are highlighted in yellow.

That's because those are auto-generated, and are bound to give you issues.

If your avi is custom built, consider giving those parameters a global parameter name in VRCFury so that you don't run into issues when updating your avi in the future.

The app will not stop you from saving VRCF parameters, but they are highlighted in yellow to let you know that it's not recommended.

## Note on Modular Avatar Parameters
Modular Avatar parameters are left in green, because they are much less volatile than VRCF.

MA uses a SHA256 hash that uses the path to the object containing the `MA Menu Item` component (excluding the root). This means that if the menu item is shared amongst all your avis, and the path is the same, then adding or removing other toggles will not affect the final name of the parameter. Of course, this can still give you issues, and giving them a manual name is still recommended, but they are way less likely to give you issues than VRCF parameters, whos names will change depending on your toggle count, so adding / removing toggles can easily mess you up.