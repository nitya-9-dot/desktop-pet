import io
from pathlib import Path

from PIL import Image
from AppKit import NSImage
from Foundation import NSData


class SpriteSheet:
    def __init__(self, path, frame_count, frame_size=None):
        path = Path(path)
        if frame_count < 1:
            raise ValueError("A sprite sheet needs at least one frame.")
        if not path.is_file():
            raise FileNotFoundError(f"Sprite sheet not found: {path}")

        self.frames = []
        self.index = 0

        image = Image.open(path).convert("RGBA")

        width, height = image.size
        if width % frame_count:
            raise ValueError(
                f"{path.name} is {width}px wide, which cannot be split into "
                f"{frame_count} equal frames."
            )

        self.frame_width = width // frame_count
        self.frame_height = height
        self.frame_count = frame_count

        for i in range(frame_count):
            frame = image.crop(
                (
                    i * self.frame_width,
                    0,
                    (i + 1) * self.frame_width,
                    self.frame_height,
                )
            )

            if frame_size is not None:
                frame = frame.resize(frame_size, Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            frame.save(buffer, format="PNG")

            data = NSData.dataWithBytes_length_(
                buffer.getvalue(),
                len(buffer.getvalue()),
            )

            nsimage = NSImage.alloc().initWithData_(data)

            self.frames.append(nsimage)

    def next_frame(self):
        if not self.frames:
            raise RuntimeError("The sprite sheet contains no frames.")

        frame = self.frames[self.index]
        self.index = (self.index + 1) % len(self.frames)
        return frame

    def reset(self):
        self.index = 0
