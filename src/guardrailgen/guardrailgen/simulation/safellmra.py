"""Adapter around the installed, pinned numerical SafeLLMRA predictor.

This is experimental extrapolation with the published narrow identification
data. Its boxes supplement development motion checks; they do not certify them.
"""
import math
from pathlib import Path
import warnings


class SafeLLMRAExperimentPredictor:
    name='safellmra_experimental'
    formal_guarantee=False

    def __init__(self, data_path=None, body_frame=False):
        from pyzonotope.NLReachability import NLReachability
        self.data_path=Path(data_path or Path.home()/'SafeLLMRA/Turtlebot/pyzonotope/example')
        self.body_frame=body_frame
        self.name='safellmra_body_frame_experimental' if body_frame else 'safellmra_experimental'
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',RuntimeWarning)
            self.engine=NLReachability(str(self.data_path))

    def boxes(self,pose,plan,position_uncertainty):
        import numpy as np
        from pyzonotope.Zonotope import Zonotope
        x,y,yaw=pose
        rotation=np.array([[math.cos(yaw),-math.sin(yaw)],[math.sin(yaw),math.cos(yaw)]])
        generators=np.diag([position_uncertainty,position_uncertainty,.01,.01])
        if self.body_frame:
            # Explicit additional modeling assumption: planar pose dynamics
            # are translation/rotation equivariant. Preserve position generator
            # correlations through both rotations, rather than double-boxing.
            generators[:2,:2]=rotation.T @ generators[:2,:2]
            initial=Zonotope(np.array([0.,0.,1.,0.]).reshape(4,1),generators)
        else:
            initial=Zonotope(np.array([x,y,math.cos(yaw),math.sin(yaw)]).reshape(4,1),generators)
        states,_=self.engine.run_reachability(initial,np.asarray(plan,dtype=float))
        if len(states)!=len(plan)+1:
            raise ValueError('SafeLLMRA predictor returned an incomplete sequence')
        boxes=[]
        for state in states:
            center=np.asarray(state.center()).flatten()
            generators=np.asarray(state.generators()).copy()
            if self.body_frame:
                center[:2]=rotation@center[:2]+np.array([x,y])
                center[2:]=rotation@center[2:]
                generators[:2]=rotation@generators[:2]
                generators[2:]=rotation@generators[2:]
            radius=np.abs(generators).sum(axis=1)
            if center.shape!=(4,) or radius.shape!=(4,) or not np.isfinite(center).all() or not np.isfinite(radius).all():
                raise ValueError('Invalid SafeLLMRA reachable set')
            boxes.append((center.tolist(),radius.tolist()))
        return boxes
