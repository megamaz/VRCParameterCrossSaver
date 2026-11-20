# Avatar Parameter Cross-Saver
This is a simple tool created for people who have a main avi, and who have their outfits separated between avis. You probably have some settings that are global (aka, shared across all avis regardless of outfit), and get annoyed when those settings get reset or set to the wrong value when swapping avis. Well, this tool aims to eliminate that, and saves those global settings across avi swaps.

## Requirements
- [Python](https://www.python.org/downloads/) 3.13 or above

## Usage
1. Run the `setup.bat`. This will download necessary dependencies for the project to function.
2. Once that's done, double-click the `main.pyw`.
3. I hope the UI is intuitive enough that I don't have to explain it.

## Note on VRCFury Parameters
You'll notice that VRCFury (VRCF) parameters are highlighted in yellow. That's because those are auto-generated, and are bound to give you issues.

VRCF parameters are auto-generated and named based on the parameter count of your avatar. This is done automatically as part of VRCF's "Unlimited Parameters" feature, so that it can get greater control over how parameters are synced. If you don't give your VRCF toggles global parameter names, VRCF will *only* use the auto-generated name to sync. When updating your avatar to add or remove toggles, these auto-generated names can change, and break the saving system.

Their naming convention can also change across VRCF updates, adding another layer to this problem.

If your avi is custom built, consider giving those parameters a global parameter name in your VRCF Toggles so that you don't run into issues when updating your avi in the future.

The app will not stop you from saving VRCF parameters, but they are highlighted in yellow to let you know that it's not recommended.

## Note on Modular Avatar Parameters
Modular Avatar (MA) auto-generated parameters will also be highlighted in yellow. They are less volatile than VRCF, but can still cause issues.

MA uses a SHA256 hash that uses the path to the object containing the `MA Menu Item` component (excluding the root). This means that if the menu item is shared amongst all your avis, and the path is the same, then adding or removing other toggles will not affect the final name of the parameter. Of course, this can still give you issues, and giving them a manual name is still recommended, but they are way less likely to give you issues than VRCF parameters, whos names will change depending on your toggle count, so adding / removing toggles can easily mess you up.

Their naming convention can also change across MA updates. It is recommended that any parameters you wish to save be given a personalized global name.