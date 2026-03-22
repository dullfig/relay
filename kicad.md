That is an incredible project—a "mechanical silicon" computer. Since DPDT relays have a massive footprint compared to transistors, a standard manual layout for even a 4-bit ALU would be a nightmare.
To automate a netlist of hundreds (or thousands) of relays, you should look into Scriptable EDA and Algorithmic Placement. Traditional "click and drag" won't scale here.

1. KiCad with Python Scripting (The "Hacker" Choice)
   KiCad is likely your best bet because its .kicad_pcb files are plain text (S-expressions), and it has a robust Python API.
* The Strategy: Don't use the GUI to place components. Write a Python script that reads your netlist and places the DPDT relay footprints in a perfect grid or "logic block" clusters.
* Routing: Once placed via script, you can use the Freerouting plugin. It is an open-source autorouter that handles complex netlists surprisingly well, provided you give it enough board real estate.
2. Cadence Allegro / SKILL (The "Industrial" Choice)
   If you can get access to Allegro, it uses a language called SKILL.
* It is specifically designed for high-density automation. You can write scripts to "instantiate" logic gates (made of 2-3 relays) as reusable modules.
* Allegro PCB Designer has the most powerful "interactive autorouter" (Route Engine) which is better at handling the "spaghetti" of relay logic than cheaper tools.
3. JITX (Generative Circuit Design)
   Since you are already working with a DSL, you should look at JITX.
* Instead of drawing a schematic, you write code (in a language based on Stanza) to define your hardware.
* It uses AI-driven solvers to optimize component placement and routing based on your code constraints. It’s basically "Code-to-PCB" and fits your workflow perfectly.
4. Specialized "Sea of Relays" Approach
   Because relays are bulky, heat and power distribution (the "coil bus") will be your biggest physical bottleneck.
* SKiDL: This is a Python library that lets you skip the schematic entirely. You describe your relay computer in Python, and it outputs a netlist for KiCad.
* Topological Autorouting: Look into Topological Routers. Unlike grid-based routers, they "snake" traces through available space, which is great for the odd angles often found in relay-based "rat's nests."

Pro Tip for Relay Computers:
Since you're using DPDT relays, you'll likely have a lot of back-EMF. Automation is great for logic, but make sure your DSL or script automatically injects flyback diodes for every single coil in the netlist, or your PCB will destroy itself on the first "Hello World."
Would you like a Python snippet showing how to procedurally place a grid of footprints in KiCad, or should we look at power-draw simulations for that many coils?
