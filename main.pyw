#! ./venv/Scripts/pythonw.exe

import threading
import asyncio
import pygame
import json
import os

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

VRCHAT_IP = "127.0.0.1"
VRCHAT_IN_PORT = 9000   # VRChat receives here
VRCHAT_OUT_PORT = 9001  # VRChat sends here
FONT_SIZE = 18

client = SimpleUDPClient(VRCHAT_IP, VRCHAT_IN_PORT)

if not os.path.exists("./params.json"):
    open("./params.json", "w", encoding="utf-8").write(r"{}")

registered_params = json.load(open("./params.json", "r", encoding="utf-8"))

running = True

def set_param(name, value):
    client.send_message(
        f"/avatar/parameters/{name}",
        value
    )

def on_avatar_change(address, *args):
    global registered_params
    print(f"Avatar changed event, updating saved params.")

    for param, content in registered_params.items():
        if not content["saved"]["on_avatar_swap"]:
            continue

        print(f"Updated saved param {param} to {content['value']}")
        set_param(param, content['value'])

def on_parameter(address, *args):
    global registered_params

    value = args[0]
    address = address[len("/avatar/parameters/"):]

    existing_contents = registered_params.get(address, {"min":0, "max":1, "saved":{"on_avatar_swap": False, "on_world_swap": False}})

    registered_params[address] = {
        "value": value,
        "min": min(existing_contents["min"], value),
        "max": max(existing_contents["max"], value),
        "saved": {
            "on_avatar_swap": existing_contents['saved']['on_avatar_swap'],
            "on_world_swap": existing_contents['saved']['on_world_swap']
        }
    }


dispatcher = Dispatcher()

dispatcher.map("/avatar/change", on_avatar_change)
dispatcher.map("/avatar/parameters/*", on_parameter)

def pygame_loop():
    global running
    global registered_params
    pygame.init()
    pygame.display.set_caption("Parameter Cross-Saver")

    screen = pygame.display.set_mode((730, 600), pygame.SRCALPHA)
    font = pygame.font.SysFont(None, FONT_SIZE)
    bigger_font = pygame.font.SysFont(None, 50)
    clock = pygame.time.Clock()
    padding = (5, 5)
    offset = 50

    while running:
        screen.fill((30, 30, 30))
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break
            if event.type == pygame.MOUSEWHEEL:
                offset += event.y * 30

            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    # discover the param at that Y value
                    param_index = int((event.pos[1] - offset) / (FONT_SIZE + padding[1])) - 1
                    params = list(registered_params.keys())
                    if param_index < len(params):
                        if event.pos[0] >= 705 and event.pos[0] <= 722:
                            registered_params[params[param_index]]['saved']['on_avatar_swap'] = not registered_params[params[param_index]]['saved']['on_avatar_swap']
                        # elif event.pos[0] >= 728 and event.pos[0] <= 746:
                        #     registered_params[params[param_index]]['saved']['on_world_swap'] = not registered_params[params[param_index]]['saved']['on_world_swap']
                        
        

        index = 1

        for param, content in registered_params.items():
            padded_y_pos = (FONT_SIZE + padding[1]) * index + offset
            label_text = font.render(f"{param}", True, (255, 255, 255))
            if type(content['value']) == float:
                value_text = font.render(f"{content['value']:.4f}", True, (255, 255, 255))
            else:
                value_text = font.render(str(content['value']), True, (255, 255, 255))

            value = (content["value"] - content["min"]) / (content["max"] - content["min"])

            color = (0, 130, 0)
            pygame.draw.rect(screen, color, (0, padded_y_pos, 700 * value, FONT_SIZE))

            screen.blit(label_text, (padding[0], padded_y_pos + padding[1]/2))

            value_rect = value_text.get_rect(topright=(700, padded_y_pos + padding[1] / 2))
            screen.blit(label_text, (padding[0], padded_y_pos + padding[1]/2))
            screen.blit(value_text, value_rect)

            # saved statuses
            pygame.draw.rect(screen, (255, 255, 255), (700 + padding[0], padded_y_pos, FONT_SIZE, FONT_SIZE), 0 if content['saved']['on_avatar_swap'] else 2)
            # pygame.draw.rect(screen, (255, 255, 255), (700 + FONT_SIZE + padding[0] * 2, padded_y_pos, FONT_SIZE, FONT_SIZE), 0 if content['saved']['on_world_swap'] else 2)
            
            index += 1

        pygame.draw.rect(screen, (30, 30, 30), (0, 0, 820, 70))
        instruction_text = bigger_font.render("Check boxes on right to mark as saved.", True, (255, 255, 255))
        # checkboxes_label = font.render("on avi swap | on world swap", True, (255, 255, 255))
        screen.blit(instruction_text, (10, 10))
        # screen.blit(checkboxes_label, (653, 55))

        pygame.display.flip()
        clock.tick(60)
            

async def main():
    global running
    pygame_thread = threading.Thread(
        target=pygame_loop,
        daemon=True,
    )

    pygame_thread.start()

    loop = asyncio.get_running_loop()

    server = AsyncIOOSCUDPServer(
        ("127.0.0.1", VRCHAT_OUT_PORT),
        dispatcher,
        loop,
    )

    transport, protocol = await server.create_serve_endpoint()

    print("OSC server listening on 127.0.0.1:9001")

    try:
        on_avatar_change("reset") # to update params on app launch
        while True:
            await asyncio.sleep(1)
            if not running:
                break

    finally:
        transport.close()

        filtered_params = {}
        for param, content in registered_params.items():
            if content['saved']['on_avatar_swap']:
                filtered_params[param] = content

        json.dump(filtered_params, open("./params.json", "w", encoding="utf-8"))

if __name__ == "__main__":
    asyncio.run(main())