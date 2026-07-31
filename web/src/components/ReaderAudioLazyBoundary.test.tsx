import { render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import type { useReaderAudio } from './reader/useReaderAudio';

const featureRequested = vi.hoisted(() => vi.fn());

vi.mock('./reader/ReaderAudioFeature', () => {
  featureRequested();
  return { default: () => <div>Audio feature loaded</div> };
});

import { ReaderAudioFeatureBoundary } from './ReaderView';

it('does not request the audio feature module until the optional UI becomes active', async () => {
  const audio = {} as ReturnType<typeof useReaderAudio>;
  const { rerender } = render(<ReaderAudioFeatureBoundary active={false} audio={audio} />);

  expect(featureRequested).not.toHaveBeenCalled();

  rerender(<ReaderAudioFeatureBoundary active audio={audio} />);

  await waitFor(() => expect(featureRequested).toHaveBeenCalledTimes(1));
  expect(await screen.findByText('Audio feature loaded')).toBeInTheDocument();
});
