# Artwork

`remaldi.svg` is the standalone project logo; `remaldi.png` is its matching
256 × 256 raster version. The SVG has no font or external-resource dependencies.

To regenerate the PNG with ImageMagick installed:

```bash
magick -background none -density 384 assets/remaldi.svg -resize 256x256 -strip PNG32:assets/remaldi.png
```

This logo is separate from the GitHub social preview image. Adding it to the
README does not change the repository's social preview setting.
