#!/usr/bin/env python3
"""Capture genuine Qt hover/press/page transitions to GIF with temporary, offline demo data.

Optional tool dependency: Pillow. It is not required by the application/build.
"""
import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import mcsync as m


def capture(path):
    from PIL import Image
    if not m.QT_AVAILABLE:
        raise SystemExit('Qt runtime required')
    app=m.QApplication.instance() or m.QApplication([])
    app.setStyle('Fusion')
    frames=[]
    with tempfile.TemporaryDirectory(prefix='mcsync-motion-demo-') as folder:
        store=m.Store(Path(folder)/'data')
        store.create('CLASSIC',minecraft='1.21.1',loader='fabric',loader_version='0.16.14',notes='Демонстрация настоящих анимаций Qt; сеть отключена.')
        m.Accounts(store).add_offline('Demo')
        window=m.MainWindow(store,network_enabled=False)
        window.resize(1180,760)
        window.show()
        app.processEvents()
        start=time.monotonic();actions=set()
        while time.monotonic()-start<3.8:
            elapsed=time.monotonic()-start
            def action(key,after,callback):
                if elapsed>=after and key not in actions:
                    actions.add(key);callback()
            action('hover',0.3,lambda:window.play_btn.animate_hover(1))
            action('press',0.9,lambda:window.play_btn.animate_press(1))
            action('release',1.2,lambda:window.play_btn.animate_press(0))
            action('leave',1.5,lambda:window.play_btn.animate_hover(0))
            action('library',1.9,window.show_library)
            action('details',2.65,window.show_details)
            app.processEvents()
            tmp=Path(folder)/'frame.png'
            window.grab().save(str(tmp))
            with Image.open(tmp) as image:
                image=image.convert('RGB');image.thumbnail((944,608));frames.append(image.copy())
            time.sleep(0.04)
        window.close()
    path.parent.mkdir(parents=True,exist_ok=True)
    frames[0].save(path,save_all=True,append_images=frames[1:],duration=70,loop=0,optimize=True)
    print('Captured real Qt animation:',path)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'designs'/'motion.gif')
    capture(parser.parse_args().output)
