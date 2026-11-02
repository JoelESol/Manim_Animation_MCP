"""Example scenes demonstrating what agents can build through the MCP tools."""

from manim import Circle, DOWN, FadeIn, FadeOut, Scene, Square, Text, Create


class CircleToSquare(Scene):
    """A circle smoothly transforming into a square."""

    def construct(self) -> None:
        circle = Circle(color="BLUE")
        square = Square(color="GREEN")
        self.play(Create(circle))
        self.play(circle.animate.move_to(square).become(square, match_width=True))
        self.wait(0.5)
        self.play(FadeOut(square))


class HelloWorld(Scene):
    """Static drawing: text and shapes composed into a single frame."""

    def construct(self) -> None:
        text = Text("Hello from Manim!").scale(0.8)
        circle = Circle(color="BLUE").next_to(text, DOWN)
        self.play(FadeIn(text), Create(circle))
        self.wait(0.5)
