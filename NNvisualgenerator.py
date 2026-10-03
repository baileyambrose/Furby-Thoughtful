from PIL import Image
import random
import math
import matplotlib.pyplot as plt
import numpy as np

INPUT_IMAGE = "HUD/empty-hud.png"

# --- CANVAS SIZE IN PIXELS ---
WIDTH  = 390
HEIGHT = 320

# Layers: 4,5,5,4,1
layers = [4, 5, 6, 6, 5, 1]

# Pixel spacing
layer_x_spacing = WIDTH // (len(layers) -1)
node_y_spacing  = 50
node_radius     = 20  # pixels

rainbow = [(1,1,1),(1,1,1),(.5,.5,.5),(.3,.3,.3),(.2,.2,.2),(.1,.1,.1)]



# --- COMPUTE PIXEL POSITIONS ---
positions = []

for i, count in enumerate(layers):
    x = (i + 0) * layer_x_spacing
    total_height = (count - 1) * node_y_spacing
    y_start = (HEIGHT // 2) - (total_height // 2)
    layer_positions = [(x, y_start + j * node_y_spacing) for j in range(count)]
    positions.append(layer_positions)



for i in range(28):
    # --- FIGURE SETUP ---
    fig = plt.figure(figsize=(WIDTH/100, HEIGHT/100), dpi=100)
    ax = plt.axes()

    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    ax.set_xlim(0, WIDTH)
    ax.set_ylim(0, HEIGHT)
    ax.invert_yaxis()  # so y=0 is top-left like pixel coordinates
    ax.axis("off")

    # --- BLACK BACKGROUND ---
    ax.add_patch(
        plt.Rectangle((0, 0), WIDTH, HEIGHT, color="black", zorder=0)
    )
    ax.add_patch(
        plt.Rectangle((0, 0), WIDTH, HEIGHT, fill=False,edgecolor="white",
            linewidth=11, zorder=3)
    )
    # --- DRAW CONNECTIONS ---
    for j in range(len(layers) - 1):
        layer_a = positions[j]
        layer_b = positions[j + 1]
        for a in layer_a:
            for b in layer_b:
                color = rainbow[np.random.randint(len(rainbow))]
                ax.plot([a[0], b[0]], [a[1], b[1]], color=color, linewidth=2.5, zorder=1)

    # --- DRAW NODES ---
    for layer in positions:
        for (x, y) in layer:
            fill = np.random.choice(["white","black","black"])
            circ = plt.Circle((x, y), node_radius, fc=fill, ec="white", lw=3.5, zorder=2)
            ax.add_patch(circ)

    plt.savefig("network.png", dpi=100)
    plt.close()

    base = Image.open(INPUT_IMAGE).convert("RGBA")
    network = Image.open("network.png").convert("RGBA")

    combined = base.copy()
    combined.alpha_composite(network, dest=(20, 20))


    # DRAW WHITE SQUARE ON BASE IMAGE
    SQUARE_Y_TRANSLATION = 111.5402
    SQUARE_Y_OFFSET = 371      # top-left corner Y
    SQUARE_WIDTH = 90   # width and height of the square
    SQUARE_HEIGHT = 82

    y_index = i
    if i >=14:
        y_index = i-14
    square_y = SQUARE_Y_OFFSET + round(y_index*SQUARE_Y_TRANSLATION)

    square_x = 0
    if i >=14:
        square_x = 1080 - SQUARE_WIDTH
    for y in range(square_y, square_y + SQUARE_HEIGHT):
        for x in range(square_x, square_x + SQUARE_WIDTH):
            if 0 <= x < combined.width and 0 <= y < combined.height:
                combined.putpixel((x, y), (255, 255, 255, 255))

    OUTPUT_IMAGE = f"HUD/hud-{i}.png"
    combined.save(OUTPUT_IMAGE)
    print("Saved:", OUTPUT_IMAGE)
