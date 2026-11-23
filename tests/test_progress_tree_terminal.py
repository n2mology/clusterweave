"""Interactive tree commands preserve child status and terminal settings."""
import errno, fcntl, os, pty, select, signal, struct, subprocess, sys, termios, time, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class TerminalCommands(unittest.TestCase):
    def test_tree_default_raw_switch_and_child_exit_restore_terminal(self):
        master,slave=pty.openpty();self.addCleanup(os.close,master);self.addCleanup(os.close,slave)
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',30,80,0,0))
        before=termios.tcgetattr(slave)
        child="import time;print('GENOME_PROGRESS genome=Long_genome_name_that_is_still_readable_on_a_narrow_terminal stage=annotation percent=0 bar=[----------] message=\"Queued genome 1/1\"',flush=True);time.sleep(1);print('TOOL_RAW genome=Long tool=antismash stream=stderr diagnostic-fixture',flush=True);time.sleep(3);raise SystemExit(7)"
        proc=subprocess.Popen([sys.executable,'-B',str(ROOT/'bin/render_progress_tree.py'),'--project','fixture','--',sys.executable,'-u','-c',child],stdin=slave,stdout=slave,stderr=slave,env={**os.environ,'TERM':'xterm','LANG':'C.UTF-8'})
        self.addCleanup(lambda:proc.kill() if proc.poll() is None else None)
        output=b''
        def until(text,timeout=8):
            nonlocal output
            end=time.monotonic()+timeout
            while text not in output and time.monotonic()<end:
                if select.select([master],[],[],.1)[0]:
                    try:output+=os.read(master,65536)
                    except OSError as e:
                        if e.errno!=errno.EIO:raise
            self.assertIn(text,output)
        until(b'Queued genome 1/1')
        self.assertNotIn(b'Raw output',output)
        os.write(master,b'/raw\n');until(b'Raw output (/tree returns to progress)')
        until(b'diagnostic-fixture');os.write(master,b'/tree\n')
        self.assertEqual(proc.wait(timeout=8),7)
        while select.select([master],[],[],.1)[0]:output+=os.read(master,65536)
        self.assertIn(b'\x1b[?25h',output)
        self.assertEqual(termios.tcgetattr(slave),before)
        self.assertIn(b'Long genome name',output)

if __name__=='__main__':unittest.main()
