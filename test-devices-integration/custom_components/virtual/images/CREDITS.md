# Test camera frames

These are the frames the virtual camera hands to Home Assistant. A real camera
returns whatever it is pointing at; this one cycles through these, so a piston
that takes two snapshots produces two visibly different pictures — which is how
you can tell it fired twice rather than once.

They are ordinary photographs rather than synthetic test cards on purpose: a
camera piston that resizes, attaches or notifies should be exercised against
the kind of image it will meet in service.

## Credit

Photographs by Jeremy Coates' father, used with permission and included here
under this package's GPL-3.0 licence. `cannon.jpg` is from a historical
re-enactment.

*(Jeremy — replace this paragraph with however you'd like him named.)*

## Replacing them

Drop JPEGs in this folder and remove the ones you don't want; the camera globs
the folder in sorted order, so nothing in the code needs changing. Keep them
small — these are ~30-65 KB at 640px, and they ship with every install.
